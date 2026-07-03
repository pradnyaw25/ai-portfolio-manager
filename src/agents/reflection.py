"""Weekly lessons-learned reflection.

Reads the week's *resolved* predictions (won/lost vs SPY) and executed trades and
asks the model to synthesize concrete ``risk_lesson`` / ``mistake`` memories,
each grounded in the prediction/trade ids it came from. The lessons are ingested
into the same Qdrant memory as everything else, so they surface in the next daily
run's ``risk_lessons`` retrieval group.

Memory ids are deterministic per (week, index), so re-running a week upserts the
same points — no duplicates.
"""

import json
from datetime import date, timedelta

from src.config import DEFAULT_SECTOR, sector_for
from src.llm import complete_structured
from src.llm.schemas import ReflectionResponse
from src.memory.memory_store import FundMemoryStore
from src.memory.schemas import MemoryIngestionResult, MemoryRecord
from src.storage.prediction_store import PredictionStore
from src.storage.trade_store import TradeStore
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "reflection/v1"
WINDOW_DAYS = 7


class ReflectionAgent:
    def reflect(self, predictions: list[dict], trades: list[dict]) -> ReflectionResponse:
        prompt = (
            "You are the fund's reflection analyst. Review the past week's RESOLVED "
            "predictions (scored win/loss versus SPY) and executed trades, and distill "
            "a few CONCRETE, non-generic lessons that would improve future decisions.\n\n"
            "Classify each as:\n"
            "  - 'mistake': a specific error the fund made (e.g. sized into a losing "
            "concentrated bet).\n"
            "  - 'risk_lesson': a forward-looking guardrail worth remembering.\n\n"
            "Ground every lesson in the evidence: put the exact source ids it derives "
            "from in 'cited_ids'. Do not invent outcomes not shown below.\n\n"
            f"Resolved predictions:\n{json.dumps(predictions, default=str)[:6000]}\n\n"
            f"Executed trades:\n{json.dumps(trades, default=str)[:4000]}\n\n"
            'Return JSON: {"lessons": [{"lesson_type": "risk_lesson"|"mistake", '
            '"content": "...", "symbols": ["AAPL"], "cited_ids": ["prediction:ab12"]}]}'
        )
        return complete_structured(
            [{"role": "user", "content": prompt}],
            ReflectionResponse,
            tier="strong",
            prompt_version=PROMPT_VERSION,
        )


def _in_window(day: str, start: str, end: str) -> bool:
    return bool(day) and start <= day <= end


def gather_week(
    week_end: str,
    *,
    prediction_store: PredictionStore,
    trade_store: TradeStore,
) -> tuple[str, list[dict], list[dict]]:
    """Return (week_start, resolved predictions, trades) for the 7-day window."""
    week_start = (date.fromisoformat(week_end) - timedelta(days=WINDOW_DAYS - 1)).isoformat()

    predictions = [
        {
            "id": f"prediction:{p.get('id')}",
            "symbol": p.get("symbol"),
            "thesis": p.get("thesis") or p.get("prediction"),
            "confidence": p.get("confidence"),
            "outcome": "WIN" if (p.get("result") or {}).get("outperformed") else "LOSS",
            "alpha": (p.get("result") or {}).get("alpha"),
        }
        for p in prediction_store.load_all()
        if p.get("status") == "scored"
        and _in_window((p.get("result") or {}).get("scored_date", ""), week_start, week_end)
    ]

    trades = [
        {
            "id": f"trade:{t.get('run_id')}:{t.get('symbol')}:{t.get('action')}",
            "symbol": t.get("symbol"),
            "action": t.get("action"),
            "shares": t.get("shares"),
            "reasoning": t.get("reasoning"),
        }
        for t in trade_store.load_all()
        if _in_window(str(t.get("date", "")), week_start, week_end)
    ]

    return week_start, predictions, trades


def build_lesson_records(
    response: ReflectionResponse,
    *,
    week_start: str,
    week_end: str,
) -> list[MemoryRecord]:
    """Turn synthesized lessons into deterministic, citable memory records."""
    records: list[MemoryRecord] = []
    for index, lesson in enumerate(response.lessons):
        content = (lesson.content or "").strip()
        if not content:
            continue
        symbols = [str(s).upper() for s in lesson.symbols if str(s).strip()]
        sectors = sorted({sector_for(s) for s in symbols} - {DEFAULT_SECTOR})
        records.append(
            MemoryRecord(
                id=f"{lesson.lesson_type}:reflection:{week_end}:{index}",
                memory_type=lesson.lesson_type,
                content=content,
                date=week_end,
                run_id=None,
                symbols=symbols,
                sectors=sectors,
                source_type="reflection",
                source_id=f"reflection:{week_end}",
                metadata={
                    "week_start": week_start,
                    "week_end": week_end,
                    "cited_ids": [str(c) for c in lesson.cited_ids],
                },
            )
        )
    return records


def ingest_lessons(
    records: list[MemoryRecord],
    *,
    store_factory=FundMemoryStore,
) -> MemoryIngestionResult:
    """Upsert lesson records into memory (idempotent — deterministic ids)."""
    if not records:
        return MemoryIngestionResult(status="skipped")
    try:
        created = store_factory().upsert_records(records)
    except Exception as exc:
        logger.warning("Reflection ingestion unavailable: %s", exc)
        return MemoryIngestionResult(status="unavailable", errors=[str(exc)])
    logger.info("Ingested %d reflection lesson(s)", created)
    return MemoryIngestionResult(status="ok", created=created)
