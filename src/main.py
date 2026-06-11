from src.config import INITIAL_CAPITAL
from src.storage.portfolio_store import PortfolioStore
from src.storage.trade_store import TradeStore
from src.storage.decision_store import DecisionStore
from src.data_sources.market_data import MarketDataClient
from src.data_sources.news import NewsClient
from src.data_sources.benchmarks import BenchmarkClient
from src.agents.researcher import ResearchAgent
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.agents.tweet_generator import TweetGeneratorAgent
from src.agents.risk_manager import RiskManagerAgent
from src.agents.rebalance_checker import RebalanceChecker
from src.models.prediction import Outlook, PortfolioDecision
from src.simulator.portfolio_engine import PortfolioEngine
from src.simulator.performance import PerformanceTracker
from src.reporting.markdown_report import MarkdownReportGenerator
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run_daily_cycle():
    logger.info("Starting daily portfolio cycle")

    portfolio_store = PortfolioStore()
    trade_store = TradeStore()
    portfolio = portfolio_store.load()

    if portfolio is None:
        engine = PortfolioEngine(initial_capital=INITIAL_CAPITAL)
    else:
        engine = PortfolioEngine.from_portfolio(portfolio)

    market_data = MarketDataClient()
    news_client = NewsClient()
    benchmark_client = BenchmarkClient()

    engine.mark_to_market(market_data)

    # 1. Research
    researcher = ResearchAgent()
    research = researcher.analyze(
        holdings=engine.get_holdings(),
        market_data=market_data,
        news_client=news_client,
    )

    # 2. Decision
    manager = PortfolioManagerAgent()
    decisions = manager.decide(
        portfolio=engine.get_snapshot(),
        research=research,
        benchmark=benchmark_client.get_sp500_performance(),
    )

    # 3. Risk check
    risk_manager = RiskManagerAgent()
    risk_review = risk_manager.review(
        raw_trades=decisions.get("trades", []),
        portfolio=engine.get_snapshot(),
        prices=research.get("prices", {}),
    )

    # 4. Rebalance check
    rebalance = RebalanceChecker()
    rebalance_result = rebalance.check(
        portfolio=engine.get_snapshot(),
        approved_trades=risk_review.approved,
        prices=research.get("prices", {}),
        research=research,
    )
    all_approved = risk_review.approved + rebalance_result.extra_trades

    # 5. Execute
    trades = engine.execute_trades(all_approved, market_data)
    for trade in trades:
        trade_store.save(trade)

    # 6. Journal
    DecisionStore().save(
        portfolio=engine.get_snapshot(),
        raw_decision=decisions,
        approved=risk_review.approved,
        rejected=risk_review.rejected,
        executed=trades,
        cash_thesis=rebalance_result.cash_thesis or decisions.get("cash_thesis"),
        rebalance_trades=rebalance_result.extra_trades,
    )

    snapshot = engine.get_snapshot()
    portfolio_store.save(snapshot)

    perf = PerformanceTracker()
    perf.record(snapshot)

    portfolio_decision = PortfolioDecision(
        reasoning=decisions.get("summary", ""),
        trades=risk_review.approved,
        outlook=Outlook(decisions["outlook"]) if "outlook" in decisions else Outlook.NEUTRAL,
        risk_assessment=decisions.get("risk_assessment", ""),
    )

    report_gen = MarkdownReportGenerator()
    report_gen.generate(snapshot, trades, research, portfolio_decision)

    tweet_agent = TweetGeneratorAgent()
    tweet = tweet_agent.generate(snapshot, trades)
    logger.info("Generated tweet: %s", tweet)

    logger.info("Daily cycle complete. Portfolio value: $%.2f", snapshot.total_value)


if __name__ == "__main__":
    run_daily_cycle()
