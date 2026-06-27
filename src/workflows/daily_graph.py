from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.models.run_state import PortfolioRunState
from src.utils.logger import get_logger
from src.utils.run_id import create_run_id, utc_now_iso
from src import main as steps

logger = get_logger(__name__)


class DailyGraphState(TypedDict):
    run: PortfolioRunState


def create_initial_state() -> DailyGraphState:
    return {
        "run": PortfolioRunState(
            run_id=create_run_id(),
            started_at=utc_now_iso(),
        )
    }


def build_daily_cycle_graph():
    graph = StateGraph(DailyGraphState)

    graph.add_node("load_portfolio", load_portfolio_node)
    graph.add_node("create_clients", create_clients_node)
    graph.add_node("mark_to_market", mark_to_market_node)
    graph.add_node("build_research_context", build_research_context_node)
    graph.add_node("retrieve_memory", retrieve_memory_node)
    graph.add_node("decide_trades", decide_trades_node)
    graph.add_node("review_risk", review_risk_node)
    graph.add_node("check_rebalance", check_rebalance_node)
    graph.add_node("execute_trades", execute_trades_node)
    graph.add_node("track_predictions", track_predictions_node)
    graph.add_node("journal_run", journal_run_node)
    graph.add_node("save_portfolio", save_portfolio_node)
    graph.add_node("generate_outputs", generate_outputs_node)
    graph.add_node("build_run_status", build_run_status_node)
    graph.add_node("export_public_artifacts", export_public_artifacts_node)

    graph.add_edge(START, "load_portfolio")
    graph.add_edge("load_portfolio", "create_clients")
    graph.add_edge("create_clients", "mark_to_market")
    graph.add_edge("mark_to_market", "build_research_context")
    graph.add_edge("build_research_context", "retrieve_memory")
    graph.add_edge("retrieve_memory", "decide_trades")
    graph.add_edge("decide_trades", "review_risk")
    graph.add_edge("review_risk", "check_rebalance")
    graph.add_edge("check_rebalance", "execute_trades")
    graph.add_edge("execute_trades", "track_predictions")
    graph.add_edge("track_predictions", "journal_run")
    graph.add_edge("journal_run", "save_portfolio")
    graph.add_edge("save_portfolio", "generate_outputs")
    graph.add_edge("generate_outputs", "build_run_status")
    graph.add_edge("build_run_status", "export_public_artifacts")
    graph.add_edge("export_public_artifacts", END)

    return graph.compile()


def run_daily_cycle_graph() -> PortfolioRunState:
    state = create_initial_state()
    run = state["run"]
    logger.info("Starting LangGraph daily portfolio cycle run_id=%s", run.run_id)

    result = build_daily_cycle_graph().invoke(state)
    final_run = result["run"]

    logger.info(
        "LangGraph daily cycle complete run_id=%s Portfolio value: $%.2f",
        final_run.run_id,
        final_run.snapshot.total_value,
    )
    return final_run


def load_portfolio_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.portfolio_store, run.trade_store, run.engine = steps.load_portfolio()
    return {"run": run}


def create_clients_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.market_data, run.news_client, run.benchmark_client = steps.create_clients()
    return {"run": run}


def mark_to_market_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    steps.mark_to_market_and_score_predictions(run.engine, run.market_data)
    return {"run": run}


def build_research_context_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.research, run.prices = steps.build_research_context(
        run.engine,
        run.market_data,
        run.news_client,
    )
    return {"run": run}


def retrieve_memory_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.memory_result, run.memory_context = steps.retrieve_memory_context()
    return {"run": run}


def decide_trades_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.decisions = steps.decide_trades(
        run.engine,
        run.research,
        run.benchmark_client,
        run.memory_context,
    )
    return {"run": run}


def review_risk_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.risk_review = steps.review_risk(run.decisions, run.engine, run.prices)
    return {"run": run}


def check_rebalance_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.rebalance_result, run.approved_trades = steps.check_rebalance(
        run.engine,
        run.risk_review,
        run.prices,
        run.research,
    )
    return {"run": run}


def execute_trades_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.trades = steps.execute_trades(
        run.engine,
        run.approved_trades,
        run.market_data,
        run.trade_store,
        run.run_id,
    )
    return {"run": run}


def track_predictions_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    steps.track_buy_predictions(run.trades, run.approved_trades, run.market_data)
    return {"run": run}


def journal_run_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    steps.journal_run(
        engine=run.engine,
        decisions=run.decisions,
        risk_review=run.risk_review,
        rebalance_result=run.rebalance_result,
        trades=run.trades,
        memory_context=run.memory_context,
        memory_result=run.memory_result,
        run_id=run.run_id,
    )
    return {"run": run}


def save_portfolio_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.snapshot = run.engine.get_snapshot()
    steps.save_portfolio_and_performance(run.portfolio_store, run.snapshot, run.market_data)
    return {"run": run}


def generate_outputs_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.report_markdown, run.tweet = steps.generate_report_and_tweet(
        snapshot=run.snapshot,
        trades=run.trades,
        research=run.research,
        decisions=run.decisions,
        approved_trades=run.risk_review.approved,
        run_id=run.run_id,
    )
    return {"run": run}


def build_run_status_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.run_status = steps.build_run_status(
        run_id=run.run_id,
        started_at=run.started_at,
        memory_result=run.memory_result,
        memory_context=run.memory_context,
        trades=run.trades,
        snapshot=run.snapshot,
    )
    return {"run": run}


def export_public_artifacts_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    steps.export_public_artifacts(
        run.snapshot,
        run.trades,
        run.tweet,
        run.report_markdown,
        run.run_id,
        run.run_status,
    )
    return {"run": run}
