"""Weekly reflection graph: gather → reflect → ingest.

A small LangGraph that reads the week's resolved predictions/trades, synthesizes
lessons, and ingests them. Conditionally skips straight to the end when the week
has nothing to reflect on. Dependencies (agent, stores, memory store factory) are
injectable so the whole graph runs in tests without an API key or Qdrant.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.reflection import (
    ReflectionAgent,
    build_lesson_records,
    gather_week,
    ingest_lessons,
)
from src.config import validate_config
from src.llm.context import set_run_id
from src.memory.memory_store import FundMemoryStore
from src.memory.schemas import MemoryIngestionResult, MemoryRecord
from src.observability import tracing
from src.storage.prediction_store import PredictionStore
from src.storage.trade_store import TradeStore
from src.utils.logger import get_logger
from src.utils.run_id import create_run_id

logger = get_logger(__name__)


@dataclass
class ReflectionRunState:
    run_id: str
    week_end: str
    agent: Any
    prediction_store: Any
    trade_store: Any
    store_factory: Callable[[], Any]
    week_start: str = ""
    predictions: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    records: list[MemoryRecord] = field(default_factory=list)
    result: MemoryIngestionResult | None = None
    errors: list[str] = field(default_factory=list)


class WeeklyGraphState(TypedDict):
    run: ReflectionRunState


def guarded_node(node_name, node_func):
    def wrapped(state: WeeklyGraphState) -> WeeklyGraphState:
        run = state["run"]
        if run.errors:
            return {"run": run}
        with tracing.span(node_name):
            try:
                return node_func(state)
            except Exception as exc:
                logger.exception("Reflection node failed node=%s", node_name)
                run.errors.append(f"{node_name}: {exc}")
                run.result = MemoryIngestionResult(status="unavailable", errors=[str(exc)])
                return {"run": run}

    return wrapped


def gather_node(state: WeeklyGraphState) -> WeeklyGraphState:
    run = state["run"]
    run.week_start, run.predictions, run.trades = gather_week(
        run.week_end,
        prediction_store=run.prediction_store,
        trade_store=run.trade_store,
    )
    return {"run": run}


def reflect_node(state: WeeklyGraphState) -> WeeklyGraphState:
    run = state["run"]
    response = run.agent.reflect(run.predictions, run.trades)
    run.records = build_lesson_records(
        response, week_start=run.week_start, week_end=run.week_end
    )
    return {"run": run}


def ingest_node(state: WeeklyGraphState) -> WeeklyGraphState:
    run = state["run"]
    run.result = ingest_lessons(run.records, store_factory=run.store_factory)
    return {"run": run}


def skip_node(state: WeeklyGraphState) -> WeeklyGraphState:
    run = state["run"]
    run.result = MemoryIngestionResult(status="skipped")
    logger.info("No resolved predictions or trades for week ending %s", run.week_end)
    return {"run": run}


def route_after_gather(state: WeeklyGraphState) -> str:
    run = state["run"]
    if run.errors:
        return "skip"
    return "reflect" if (run.predictions or run.trades) else "skip"


def build_weekly_reflection_graph():
    graph = StateGraph(WeeklyGraphState)
    graph.add_node("gather", guarded_node("gather", gather_node))
    graph.add_node("reflect", guarded_node("reflect", reflect_node))
    graph.add_node("ingest", guarded_node("ingest", ingest_node))
    graph.add_node("skip", skip_node)

    graph.add_edge(START, "gather")
    graph.add_conditional_edges("gather", route_after_gather, {"reflect": "reflect", "skip": "skip"})
    graph.add_edge("reflect", "ingest")
    graph.add_edge("ingest", END)
    graph.add_edge("skip", END)
    return graph.compile()


def run_weekly_reflection_graph(
    *,
    week_end: str | None = None,
    agent: Any = None,
    prediction_store: Any = None,
    trade_store: Any = None,
    store_factory: Callable[[], Any] = FundMemoryStore,
) -> MemoryIngestionResult:
    validate_config()
    run_id = create_run_id()
    set_run_id(run_id)
    state = {
        "run": ReflectionRunState(
            run_id=run_id,
            week_end=week_end or date.today().isoformat(),
            agent=agent or ReflectionAgent(),
            prediction_store=prediction_store or PredictionStore(),
            trade_store=trade_store or TradeStore(),
            store_factory=store_factory,
        )
    }
    with tracing.trace_run(run_id):
        result = build_weekly_reflection_graph().invoke(state)
    return result["run"].result or MemoryIngestionResult(status="skipped")
