"""Daily-cycle step functions.

Each function here is one step of the daily portfolio cycle (load, mark-to-market,
research, decide, risk-review, execute, journal, report, export, ...). The
LangGraph runner in :mod:`src.workflows.daily_graph` imports this module as
``steps`` and wires the functions into graph nodes — that graph is the single
entrypoint for a run (``scripts/daily_run.py``). This module intentionally has no
orchestration or ``__main__`` of its own.
"""

from src.config import INITIAL_CAPITAL
from src.llm.cost import summarize_run_cost
from src.storage.run_history_store import RunHistoryStore
from src.storage.portfolio_store import PortfolioStore
from src.storage.trade_store import TradeStore
from src.storage.decision_store import DecisionStore
from src.data_sources.market_data import MarketDataClient
from src.data_sources.news import NewsClient
from src.data_sources.benchmarks import BenchmarkClient
from src.research.market_context import MarketContextBuilder
from src.agents.debate import run_debate
from src.agents.tweet_generator import TweetGeneratorAgent
from src.agents.risk_manager import RiskManagerAgent
from src.agents.rebalance_checker import RebalanceChecker
from src.models.prediction import Outlook, PortfolioDecision
from src.simulator.portfolio_engine import PortfolioEngine
from src.simulator.performance import PerformanceTracker
from src.reporting.markdown_report import MarkdownReportGenerator
from src.reporting.public_exporter import PublicExporter
from src.storage.prediction_store import PredictionStore
from src.scoring.prediction_scorer import PredictionScorer
from src.utils.logger import get_logger
from src.utils.run_id import utc_now_iso
from src.simulator.benchmark_tracker import BenchmarkTracker
from src.memory.retriever import format_grouped_memory_for_prompt, retrieve_grouped_fund_memory
from src.memory.ingestion_service import ingest_run_memory as ingest_run_memory_service
from src.memory.citations import review_memory_citations
from src.scoring.grounding import check_grounding
from src.social.twitter import TweetPublishResult, publish_tweet as publish_tweet_service

logger = get_logger(__name__)

MEMORY_QUERY = (
    "Relevant prior investment theses, trades, cash decisions, "
    "risk concerns, and portfolio lessons for today's decision."
)


def load_portfolio():
    portfolio_store = PortfolioStore()
    trade_store = TradeStore()
    portfolio = portfolio_store.load()

    if portfolio is None:
        logger.info("No saved portfolio found — initializing fresh with $%.2f", INITIAL_CAPITAL)
        engine = PortfolioEngine(initial_capital=INITIAL_CAPITAL)
    else:
        engine = PortfolioEngine.from_portfolio(portfolio)

    logger.info(
        "Loaded portfolio: cash=$%.2f positions=%d total=$%.2f",
        engine.cash,
        len(engine.positions),
        engine.get_snapshot().total_value,
    )
    return portfolio_store, trade_store, engine


def create_clients():
    return MarketDataClient(), NewsClient(), BenchmarkClient()


def mark_to_market_and_score_predictions(engine, market_data):
    engine.mark_to_market(market_data)

    scorer = PredictionScorer()
    scored = scorer.score_due_predictions(market_data)
    if scored:
        logger.info("Scored %d predictions", len(scored))

    logger.info(
        "After mark-to-market: cash=$%.2f total=$%.2f",
        engine.cash,
        engine.get_snapshot().total_value,
    )

    for symbol, position in list(engine.positions.items())[:5]:
        logger.info(
            "Position %s shares=%s avg=$%.2f price=$%.2f value=$%.2f",
            symbol,
            position.shares,
            position.avg_cost,
            position.current_price,
            position.market_value,
        )


def build_research_context(engine, market_data, news_client):
    context_builder = MarketContextBuilder()
    market_context = context_builder.build(
        snapshot=engine.get_snapshot(),
        market_data=market_data,
        news_client=news_client,
    )
    research = market_context.to_dict()
    return research, extract_prices(research)


def extract_prices(research: dict) -> dict[str, float]:
    prices = {}
    for sym in research.get("symbols", []):
        symbol = sym.get("symbol", "")
        price = sym.get("price")
        if price is not None and price > 0:
            prices[symbol] = price
    return prices


def retrieve_memory_context(research: dict | None = None):
    memory_result = retrieve_grouped_fund_memory(
        query=MEMORY_QUERY,
        symbols=extract_memory_symbols(research or {}),
        k_per_group=4,
    )
    memory_context = memory_result.chunks
    memory_groups = format_grouped_memory_for_prompt(memory_result.grouped)

    logger.info("Memory status=%s chunks=%d", memory_result.status, len(memory_context))
    if memory_result.error:
        logger.warning("Memory error: %s", memory_result.error)
    for item in memory_context:
        logger.info("Memory source: %s", item["metadata"])

    return memory_result, memory_context, memory_groups


def extract_memory_symbols(research: dict) -> list[str]:
    symbols = []
    for holding in research.get("holdings", []):
        symbol = holding.get("symbol")
        if symbol:
            symbols.append(str(symbol).upper())
    for symbol_context in research.get("symbols", [])[:12]:
        symbol = symbol_context.get("symbol")
        if symbol:
            symbols.append(str(symbol).upper())
    return sorted(set(symbols))


def decide_trades(engine, research, benchmark_client, memory_context):
    return run_debate(
        portfolio=engine.get_snapshot(),
        research=research,
        benchmark=benchmark_client.get_sp500_performance(),
        memory=memory_context,
    )


def review_risk(decisions, engine, prices):
    risk_manager = RiskManagerAgent()
    return risk_manager.review(
        raw_trades=decisions.get("trades", []),
        portfolio=engine.get_snapshot(),
        prices=prices,
    )


def check_rebalance(engine, risk_review, prices, research):
    rebalance = RebalanceChecker()
    rebalance_result = rebalance.check(
        portfolio=engine.get_snapshot(),
        approved_trades=risk_review.approved,
        prices=prices,
        research=research,
    )
    return rebalance_result, risk_review.approved + rebalance_result.extra_trades


def execute_trades(engine, approved_trades, market_data, trade_store, run_id):
    trades = engine.execute_trades(approved_trades, market_data)
    for trade in trades:
        trade.run_id = run_id
        trade_store.save(trade)
    return trades


def track_buy_predictions(trades, approved_trades, market_data):
    prediction_store = PredictionStore()
    try:
        spy_price = market_data.get_price("SPY")
    except Exception:
        spy_price = 0

    confidence_map = {t.symbol: t.confidence for t in approved_trades}
    for trade in trades:
        if trade.action.value == "BUY" and spy_price > 0:
            prediction_store.create_from_trade(
                trade=trade,
                confidence=confidence_map.get(trade.symbol, 0.5),
                spy_price=spy_price,
            )


def run_grounding_check(decisions, research, memory_context, snapshot):
    """Verify the decision's claims are grounded in the context it had."""
    return check_grounding(
        decisions,
        research=research,
        memory=memory_context,
        portfolio=snapshot,
    ).to_dict()


def journal_run(
    *,
    engine,
    decisions,
    risk_review,
    rebalance_result,
    trades,
    memory_context,
    memory_result,
    grounding=None,
    run_id,
):
    citation_review = review_memory_citations(
        raw_decision=decisions,
        memory_used=memory_context,
    )
    DecisionStore().save(
        portfolio=engine.get_snapshot(),
        raw_decision=decisions,
        approved=risk_review.approved,
        rejected=risk_review.rejected,
        executed=trades,
        cash_thesis=rebalance_result.cash_thesis or decisions.get("cash_thesis"),
        rebalance_trades=rebalance_result.extra_trades,
        memory_used=memory_context,
        memory_status=memory_result.status,
        memory_error=memory_result.error,
        memory_citations=citation_review.to_dict()["citations"],
        memory_citation_warnings=citation_review.warnings,
        grounding=grounding,
        run_id=run_id,
    )


def save_portfolio_and_performance(portfolio_store, snapshot, market_data):
    portfolio_store.save(snapshot)
    PerformanceTracker().record(snapshot)
    BenchmarkTracker().record(market_data)


def generate_report_and_tweet(snapshot, trades, research, decisions, approved_trades, run_id):
    portfolio_decision = PortfolioDecision(
        reasoning=decisions.get("summary", ""),
        trades=approved_trades,
        outlook=Outlook(decisions["outlook"]) if "outlook" in decisions else Outlook.NEUTRAL,
        risk_assessment=decisions.get("risk_assessment", ""),
    )

    report_markdown = MarkdownReportGenerator().generate(
        snapshot,
        trades,
        research,
        portfolio_decision,
        run_id=run_id,
    )
    tweet = TweetGeneratorAgent().generate(snapshot, trades)
    logger.info("Generated tweet: %s", tweet)
    return report_markdown, tweet


def build_run_status(run_id, started_at, memory_result, memory_context, trades, snapshot):
    warnings = []
    if memory_result.error:
        warnings.append(f"Memory unavailable: {memory_result.error}")

    return {
        "run_id": run_id,
        "status": "success",
        "started_at": started_at,
        "completed_at": utc_now_iso(),
        "memory_status": memory_result.status,
        "memory_error": memory_result.error,
        "memory_chunks": len(memory_context),
        "trades_executed": len(trades),
        "warnings": warnings,
        "errors": [],
        "memory_ingestion": None,
        "tweet_publish": None,
        "llm": summarize_run_cost(run_id),
        "portfolio_value": snapshot.total_value,
        "cash_pct": snapshot.cash_pct,
    }


def record_run_history(run_status):
    """Persist the run's final status durably and refresh the public export."""
    if not run_status:
        return
    try:
        RunHistoryStore().record(run_status)
        PublicExporter().write_run_history()
    except Exception as exc:  # run history is best-effort, never fatal
        logger.warning("Failed to record run history: %s", exc)


def build_failure_run_status(
    run_id,
    started_at,
    *,
    failed_step: str | None,
    errors: list[str],
    warnings: list[str] | None = None,
    snapshot=None,
):
    return {
        "run_id": run_id,
        "status": "failed",
        "started_at": started_at,
        "completed_at": utc_now_iso(),
        "failed_step": failed_step,
        "memory_status": None,
        "memory_error": None,
        "memory_chunks": 0,
        "trades_executed": 0,
        "warnings": warnings or [],
        "errors": errors,
        "memory_ingestion": None,
        "tweet_publish": None,
        "llm": summarize_run_cost(run_id),
        "portfolio_value": snapshot.total_value if snapshot is not None else None,
        "cash_pct": snapshot.cash_pct if snapshot is not None else None,
    }


def publish_tweet(tweet, run_id, run_status, grounding=None):
    if grounding and grounding.get("status") == "flagged":
        logger.warning("Tweet blocked — decision failed grounding check: %s", grounding.get("issues"))
        result = TweetPublishResult(
            status="blocked_grounding",
            posted=False,
            dry_run=False,
            text=tweet,
            error="decision failed grounding check",
            run_id=run_id,
        )
        run_status["tweet_publish"] = result.to_dict()
        run_status.setdefault("warnings", []).append(
            "Tweet blocked: decision failed grounding check"
        )
        return result

    result = publish_tweet_service(tweet, run_id=run_id)
    run_status["tweet_publish"] = result.to_dict()
    if result.status not in {"posted", "dry_run", "skipped"}:
        run_status.setdefault("warnings", []).append(
            f"Tweet publish status={result.status}: {result.error}"
        )
    return result


def update_tweet_publish_status(tweet_publish_result, run_status):
    exporter = PublicExporter()
    exporter.update_latest_tweet_status(tweet_publish_result.to_dict())
    exporter.write_run_status(run_status)


def ingest_run_memory(run_id, report_markdown):
    return ingest_run_memory_service(
        run_id=run_id,
        report_markdown=report_markdown,
    )


def export_run_status(run_status):
    PublicExporter().write_run_status(run_status)


def export_public_artifacts(snapshot, trades, tweet, report_markdown, run_id, run_status):
    PublicExporter().export(
        snapshot,
        trades,
        tweet,
        report_markdown,
        run_id=run_id,
        run_status=run_status,
    )
