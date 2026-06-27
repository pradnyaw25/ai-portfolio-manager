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


def run_daily_cycle():
    run_id = create_run_id()
    started_at = utc_now_iso()
    logger.info("Starting daily portfolio cycle run_id=%s", run_id)

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

    market_data = MarketDataClient()
    news_client = NewsClient()
    benchmark_client = BenchmarkClient()

    engine.mark_to_market(market_data)

    # Score any due predictions
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

    # 1. Research
    context_builder = MarketContextBuilder()
    market_context = context_builder.build(
        snapshot=engine.get_snapshot(),
        market_data=market_data,
        news_client=news_client,
    )

    research = market_context.to_dict()

    prices = {}
    for sym in research.get("symbols", []):
        symbol = sym.get("symbol", "")
        price = sym.get("price")
        if price is not None and price > 0:
            prices[symbol] = price

    # 2. Memory
    memory_result = retrieve_fund_memory(
        query=(
            "Relevant prior investment theses, trades, cash decisions, "
            "risk concerns, and portfolio lessons for today's decision."
        ),
        k=6,
    )
    memory_context = memory_result.chunks

    logger.info("Memory status=%s chunks=%d", memory_result.status, len(memory_context))
    if memory_result.error:
        logger.warning("Memory error: %s", memory_result.error)
    for item in memory_context:
        logger.info("Memory source: %s", item["metadata"])

    # 3. Decision
    manager = PortfolioManagerAgent()
    decisions = manager.decide(
        portfolio=engine.get_snapshot(),
        research=research,
        benchmark=benchmark_client.get_sp500_performance(),
        memory=memory_context
    )

    # 3. Risk check
    risk_manager = RiskManagerAgent()
    risk_review = risk_manager.review(
        raw_trades=decisions.get("trades", []),
        portfolio=engine.get_snapshot(),
        prices=prices,
    )

    # 4. Rebalance check
    rebalance = RebalanceChecker()
    rebalance_result = rebalance.check(
        portfolio=engine.get_snapshot(),
        approved_trades=risk_review.approved,
        prices=prices,
        research=research,
    )
    all_approved = risk_review.approved + rebalance_result.extra_trades

    # 5. Execute
    trades = engine.execute_trades(all_approved, market_data)
    for trade in trades:
        trade.run_id = run_id
        trade_store.save(trade)

    # 6. Track predictions for BUY trades
    prediction_store = PredictionStore()
    try:
        spy_price = market_data.get_price("SPY")
    except Exception:
        spy_price = 0

    confidence_map = {t.symbol: t.confidence for t in all_approved}
    for trade in trades:
        if trade.action.value == "BUY" and spy_price > 0:
            prediction_store.create_from_trade(
                trade=trade,
                confidence=confidence_map.get(trade.symbol, 0.5),
                spy_price=spy_price,
            )

    # 6. Journal
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

    snapshot = engine.get_snapshot()
    portfolio_store.save(snapshot)

    perf = PerformanceTracker()
    perf.record(snapshot)

    benchmark_tracker = BenchmarkTracker()
    benchmark_tracker.record(market_data)

    portfolio_decision = PortfolioDecision(
        reasoning=decisions.get("summary", ""),
        trades=risk_review.approved,
        outlook=Outlook(decisions["outlook"]) if "outlook" in decisions else Outlook.NEUTRAL,
        risk_assessment=decisions.get("risk_assessment", ""),
    )

    report_gen = MarkdownReportGenerator()
    report_markdown = report_gen.generate(snapshot, trades, research, portfolio_decision, run_id=run_id)

    tweet_agent = TweetGeneratorAgent()
    tweet = tweet_agent.generate(snapshot, trades)
    logger.info("Generated tweet: %s", tweet)

    warnings = []
    if memory_result.error:
        warnings.append(f"Memory unavailable: {memory_result.error}")

    run_status = {
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

    public_exporter = PublicExporter()
    public_exporter.export(
        snapshot,
        trades,
        tweet,
        report_markdown,
        run_id=run_id,
        run_status=run_status,
    )

    logger.info("Daily cycle complete run_id=%s Portfolio value: $%.2f", run_id, snapshot.total_value)


if __name__ == "__main__":
    run_daily_cycle()
