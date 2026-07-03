from collections.abc import Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src import config
from src.config import validate_config
from src.llm.context import set_run_id
from src.models.run_state import PortfolioRunState
from src.observability import tracing
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

    workflow_nodes = [
        ("load_portfolio", load_portfolio_node),
        ("create_clients", create_clients_node),
        ("mark_to_market", mark_to_market_node),
        ("build_research_context", build_research_context_node),
        ("retrieve_memory", retrieve_memory_node),
        ("research_followup", research_followup_node),
        ("decide_trades", decide_trades_node),
        ("check_grounding", check_grounding_node),
        ("review_risk", review_risk_node),
        ("check_rebalance", check_rebalance_node),
        ("human_approval", human_approval_node),
        ("execute_trades", execute_trades_node),
        ("track_predictions", track_predictions_node),
        ("journal_run", journal_run_node),
        ("save_portfolio", save_portfolio_node),
        ("generate_outputs", generate_outputs_node),
        ("build_run_status", build_run_status_node),
        ("export_public_artifacts", export_public_artifacts_node),
        ("publish_tweet", publish_tweet_node),
        ("ingest_run_memory", ingest_run_memory_node),
    ]

    for node_name, node_func in workflow_nodes:
        graph.add_node(node_name, guarded_node(node_name, node_func))
    graph.add_node("finalize_failure", finalize_failure_node)

    graph.add_edge(START, "load_portfolio")
    for (node_name, _), (next_node_name, _) in zip(workflow_nodes, workflow_nodes[1:]):
        graph.add_conditional_edges(
            node_name,
            route_after_node,
            {
                "ok": next_node_name,
                "failed": "finalize_failure",
            },
        )
    graph.add_conditional_edges(
        workflow_nodes[-1][0],
        route_after_node,
        {
            "ok": END,
            "failed": "finalize_failure",
        },
    )
    graph.add_edge("finalize_failure", END)

    return graph.compile()


def run_daily_cycle_graph() -> PortfolioRunState:
    validate_config()
    state = create_initial_state()
    run = state["run"]
    set_run_id(run.run_id)
    logger.info("Starting LangGraph daily portfolio cycle run_id=%s", run.run_id)

    with tracing.trace_run(run.run_id):
        result = build_daily_cycle_graph().invoke(state)
    final_run = result["run"]

    steps.record_run_history(final_run.run_status)

    if final_run.errors:
        logger.error(
            "LangGraph daily cycle failed run_id=%s failed_step=%s errors=%s",
            final_run.run_id,
            final_run.failed_step,
            final_run.errors,
        )
        return final_run

    logger.info(
        "LangGraph daily cycle complete run_id=%s Portfolio value: $%.2f",
        final_run.run_id,
        final_run.snapshot.total_value,
    )
    return final_run


def guarded_node(
    node_name: str,
    node_func: Callable[[DailyGraphState], DailyGraphState],
) -> Callable[[DailyGraphState], DailyGraphState]:
    def wrapped(state: DailyGraphState) -> DailyGraphState:
        run = state["run"]
        if run.errors:
            return {"run": run}

        with tracing.span(node_name):
            try:
                return node_func(state)
            except Exception as exc:
                logger.exception(
                    "LangGraph node failed node=%s run_id=%s",
                    node_name,
                    run.run_id,
                )
                run.failed_step = node_name
                run.errors.append(f"{node_name}: {exc}")
                run.snapshot = _snapshot_if_available(run)
                return {"run": run}

    return wrapped


def route_after_node(state: DailyGraphState) -> str:
    return "failed" if state["run"].errors else "ok"


def finalize_failure_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.snapshot = run.snapshot or _snapshot_if_available(run)
    run.run_status = steps.build_failure_run_status(
        run_id=run.run_id,
        started_at=run.started_at,
        failed_step=run.failed_step,
        errors=run.errors,
        warnings=run.warnings,
        snapshot=run.snapshot,
    )
    steps.export_run_status(run.run_status)
    return {"run": run}


def _snapshot_if_available(run: PortfolioRunState):
    if run.snapshot is not None:
        return run.snapshot
    if run.engine is None:
        return None
    try:
        return run.engine.get_snapshot()
    except Exception:
        return None


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
    run.memory_result, run.memory_context, run.memory_groups = steps.retrieve_memory_context(run.research)
    return {"run": run}


def research_followup_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.research_brief = steps.run_research_followup(
        run.engine,
        run.market_data,
        run.news_client,
        run.research,
        run.memory_context,
    )
    return {"run": run}


def decide_trades_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.decisions = steps.decide_trades(
        run.engine,
        run.research,
        run.benchmark_client,
        run.memory_groups,
    )
    return {"run": run}


def check_grounding_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    run.grounding = steps.run_grounding_check(
        run.decisions,
        run.research,
        run.memory_context,
        run.engine.get_snapshot(),
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


def _serialize_pending_trade(trade) -> dict:
    action = getattr(trade, "action", None)
    return {
        "symbol": getattr(trade, "symbol", None),
        "action": getattr(action, "value", action),
        "shares": getattr(trade, "shares", None),
        "confidence": getattr(trade, "confidence", None),
        "reason": getattr(trade, "reasoning", getattr(trade, "reason", "")),
    }


def prompt_for_approval(pending: list[dict]) -> dict:
    """Show pending trades and read the operator's decision from the terminal.

    Returns approve (execute all), reject (veto all), or edit (execute only the
    kept indices). Falls back to a safe reject when there is no interactive
    terminal, so a run is never executed without an explicit human OK.
    """
    print(f"\n{len(pending)} trade(s) pending approval:\n")
    for i, trade in enumerate(pending):
        print(
            f"  [{i}] {trade.get('action')} {trade.get('shares')} {trade.get('symbol')} "
            f"(confidence {trade.get('confidence')}) — {trade.get('reason')}"
        )
    print()

    try:
        choice = input("Action — [a]pprove all / [r]eject all / [e]dit subset? ").strip().lower()
        if choice.startswith("r"):
            reason = input("Reason for veto (optional): ").strip() or None
            return {"action": "reject", "reason": reason}
        if choice.startswith("e"):
            raw = input("Indices to KEEP (comma-separated, e.g. 0,2): ").strip()
            keep = [int(i) for i in raw.split(",") if i.strip() != ""]
            return {"action": "edit", "approved_indices": keep}
        return {"action": "approve"}
    except EOFError:
        logger.warning("No interactive terminal for approval — vetoing trades for safety.")
        return {"action": "reject", "reason": "no interactive approver"}


def human_approval_node(state: DailyGraphState) -> DailyGraphState:
    """Optional human-in-the-loop gate between risk review and execution.

    With AUTO_APPROVE on (default), this is a pass-through so scheduled/CI runs
    are unattended. With it off, the node blocks and prompts the operator in the
    terminal (``prompt_for_approval``) for a decision: approve (execute all),
    reject (veto all), or edit (execute a chosen subset). Blocking inline keeps
    the run state in memory — no checkpoint serialization of live handles.
    """
    run = state["run"]

    if config.AUTO_APPROVE or not run.approved_trades:
        run.human_review = {
            "decision": "auto_approved",
            "pending": len(run.approved_trades),
        }
        return {"run": run}

    decision = prompt_for_approval([_serialize_pending_trade(t) for t in run.approved_trades])

    action = decision.get("action", "approve")
    if action == "reject":
        run.human_review = {"decision": "reject", "reason": decision.get("reason")}
        run.approved_trades = []
    elif action == "edit":
        keep = set(decision.get("approved_indices", []))
        kept = [t for i, t in enumerate(run.approved_trades) if i in keep]
        run.human_review = {
            "decision": "edit",
            "kept": len(kept),
            "original": len(run.approved_trades),
        }
        run.approved_trades = kept
    else:
        run.human_review = {"decision": "approve", "approved": len(run.approved_trades)}

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
        grounding=run.grounding,
        research_brief=run.research_brief,
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
    run.run_status["human_review"] = run.human_review
    run.warnings = list(run.run_status.get("warnings", []))
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


def publish_tweet_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    try:
        run.tweet_publish_result = steps.publish_tweet(
            run.tweet,
            run.run_id,
            run.run_status,
            grounding=run.grounding,
        )
        steps.update_tweet_publish_status(run.tweet_publish_result, run.run_status)
        run.warnings = list(run.run_status.get("warnings", []))
    except Exception as exc:
        logger.warning("Tweet publishing failed unexpectedly run_id=%s error=%s", run.run_id, exc)
        run.warnings.append(f"Tweet publishing failed: {exc}")
        run.run_status["warnings"] = run.warnings
        run.run_status["tweet_publish"] = {
            "status": "error",
            "posted": False,
            "dry_run": False,
            "tweet_id": None,
            "text": run.tweet,
            "error": str(exc),
            "created_at": None,
            "run_id": run.run_id,
        }
        steps.export_run_status(run.run_status)
    return {"run": run}


def ingest_run_memory_node(state: DailyGraphState) -> DailyGraphState:
    run = state["run"]
    try:
        run.memory_ingestion_result = steps.ingest_run_memory(
            run.run_id,
            run.report_markdown,
        )
    except Exception as exc:
        logger.warning("Memory ingestion failed unexpectedly run_id=%s error=%s", run.run_id, exc)
        run.warnings.append(f"Memory ingestion failed: {exc}")
        run.run_status["memory_ingestion"] = {
            "status": "unavailable",
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [str(exc)],
            "total_processed": 0,
        }
        steps.export_run_status(run.run_status)
        return {"run": run}

    ingestion_status = run.memory_ingestion_result.to_dict()
    run.run_status["memory_ingestion"] = ingestion_status
    if run.memory_ingestion_result.status not in {"ok", "skipped"}:
        warning = "Memory ingestion unavailable"
        if run.memory_ingestion_result.errors:
            warning = f"{warning}: {run.memory_ingestion_result.errors[0]}"
        run.warnings.append(warning)
        run.run_status["warnings"] = run.warnings

    steps.export_run_status(run.run_status)
    return {"run": run}
