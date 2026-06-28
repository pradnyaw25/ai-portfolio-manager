from src.config import INITIAL_CAPITAL
from src.storage.portfolio_store import PortfolioStore
from src.storage.trade_store import TradeStore
from src.storage.decision_store import DecisionStore
from src.data_sources.market_data import MarketDataClient
from src.data_sources.news import NewsClient
from src.data_sources.benchmarks import BenchmarkClient
from src.research.market_context import MarketContextBuilder
from src.agents.portfolio_manager import PortfolioManagerAgent
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
from src.utils.run_id import create_run_id, utc_now_iso
from src.simulator.benchmark_tracker import BenchmarkTracker
from src.memory.retriever import retrieve_fund_memory

logger = get_logger(__name__)

MEMORY_QUERY = (
    "Relevant prior investment theses, trades, cash decisions, "
    "risk concerns, and portfolio lessons for today's decision."
)


def run_daily_cycle():
    run_id = create_run_id()
    started_at = utc_now_iso()
    logger.info("Starting daily portfolio cycle run_id=%s", run_id)

    portfolio_store, trade_store, engine = load_portfolio()
    market_data, news_client, benchmark_client = create_clients()

    mark_to_market_and_score_predictions(engine, market_data)
    research, prices = build_research_context(engine, market_data, news_client)
    memory_result, memory_context = retrieve_memory_context()
    decisions = decide_trades(engine, research, benchmark_client, memory_context)
    risk_review = review_risk(decisions, engine, prices)
    rebalance_result, all_approved = check_rebalance(engine, risk_review, prices, research)
    trades = execute_trades(engine, all_approved, market_data, trade_store, run_id)
    track_buy_predictions(trades, all_approved, market_data)
    journal_run(
        engine=engine,
        decisions=decisions,
        risk_review=risk_review,
        rebalance_result=rebalance_result,
        trades=trades,
        memory_context=memory_context,
        memory_result=memory_result,
        run_id=run_id,
    )

    snapshot = engine.get_snapshot()
    save_portfolio_and_performance(portfolio_store, snapshot, market_data)
    report_markdown, tweet = generate_report_and_tweet(
        snapshot=snapshot,
        trades=trades,
        research=research,
        decisions=decisions,
        approved_trades=risk_review.approved,
        run_id=run_id,
    )
    run_status = build_run_status(
        run_id=run_id,
        started_at=started_at,
        memory_result=memory_result,
        memory_context=memory_context,
        trades=trades,
        snapshot=snapshot,
    )
    export_public_artifacts(snapshot, trades, tweet, report_markdown, run_id, run_status)

    logger.info("Daily cycle complete run_id=%s Portfolio value: $%.2f", run_id, snapshot.total_value)


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


def retrieve_memory_context():
    memory_result = retrieve_fund_memory(query=MEMORY_QUERY, k=6)
    memory_context = memory_result.chunks

    logger.info("Memory status=%s chunks=%d", memory_result.status, len(memory_context))
    if memory_result.error:
        logger.warning("Memory error: %s", memory_result.error)
    for item in memory_context:
        logger.info("Memory source: %s", item["metadata"])

    return memory_result, memory_context


def decide_trades(engine, research, benchmark_client, memory_context):
    manager = PortfolioManagerAgent()
    return manager.decide(
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


def journal_run(
    *,
    engine,
    decisions,
    risk_review,
    rebalance_result,
    trades,
    memory_context,
    memory_result,
    run_id,
):
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
        "portfolio_value": snapshot.total_value,
        "cash_pct": snapshot.cash_pct,
    }


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
        "portfolio_value": snapshot.total_value if snapshot is not None else None,
        "cash_pct": snapshot.cash_pct if snapshot is not None else None,
    }


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


if __name__ == "__main__":
    run_daily_cycle()
