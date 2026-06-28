from collections.abc import Callable
from datetime import date

from src.memory.extractors import (
    extract_decision_memories,
    extract_report_memories,
    extract_trade_memory,
)
from src.memory.memory_store import FundMemoryStore
from src.memory.schemas import MemoryIngestionResult, MemoryRecord
from src.storage.decision_store import DecisionStore
from src.storage.trade_store import TradeStore
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryIngestionService:
    def __init__(
        self,
        store_factory: Callable[[], FundMemoryStore] = FundMemoryStore,
        decision_store: DecisionStore | None = None,
        trade_store: TradeStore | None = None,
    ):
        self.store_factory = store_factory
        self.decision_store = decision_store or DecisionStore()
        self.trade_store = trade_store or TradeStore()

    def ingest_run(
        self,
        *,
        run_id: str,
        report_markdown: str = "",
        report_date: str | None = None,
    ) -> MemoryIngestionResult:
        records = self.collect_run_records(
            run_id=run_id,
            report_markdown=report_markdown,
            report_date=report_date,
        )
        return self.ingest_records(records)

    def collect_run_records(
        self,
        *,
        run_id: str,
        report_markdown: str = "",
        report_date: str | None = None,
    ) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        records.extend(
            extract_report_memories(
                report_markdown=report_markdown,
                run_id=run_id,
                report_date=report_date or date.today().isoformat(),
            )
        )

        for decision in self.decision_store.load_all():
            if decision.get("run_id") == run_id:
                records.extend(extract_decision_memories(decision))

        for trade in self.trade_store.load_all():
            if trade.get("run_id") == run_id:
                memory = extract_trade_memory(trade)
                if memory is not None:
                    records.append(memory)

        return _dedupe_records(records)

    def ingest_records(self, records: list[MemoryRecord]) -> MemoryIngestionResult:
        if not records:
            return MemoryIngestionResult(status="skipped", skipped=0)

        try:
            upserted = self.store_factory().upsert_records(records)
        except Exception as exc:
            logger.warning("Memory ingestion unavailable; continuing without update: %s", exc)
            return MemoryIngestionResult(status="unavailable", errors=[str(exc)])

        return MemoryIngestionResult(status="ok", created=upserted)


def ingest_run_memory(
    *,
    run_id: str,
    report_markdown: str = "",
    report_date: str | None = None,
) -> MemoryIngestionResult:
    return MemoryIngestionService().ingest_run(
        run_id=run_id,
        report_markdown=report_markdown,
        report_date=report_date,
    )


def _dedupe_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    deduped: dict[str, MemoryRecord] = {}
    for record in records:
        deduped[record.id] = record
    return list(deduped.values())
