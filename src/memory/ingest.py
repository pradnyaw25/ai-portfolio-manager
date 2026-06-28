import re

from src.config import REPORTS_DIR
from src.memory.extractors import (
    extract_decision_memories,
    extract_report_memories,
    extract_trade_memory,
)
from src.memory.ingestion_service import MemoryIngestionService
from src.storage.decision_store import DecisionStore
from src.storage.trade_store import TradeStore

RUN_ID_PATTERN = re.compile(r"\*\*Run ID:\*\* `([^`]+)`")


def load_backfill_records():
    records = []

    for path in sorted(REPORTS_DIR.glob("report_*.md")):
        report_markdown = path.read_text()
        report_date = path.stem.replace("report_", "")
        run_id = _extract_run_id(report_markdown) or f"report_{report_date}"
        records.extend(
            extract_report_memories(
                report_markdown=report_markdown,
                run_id=run_id,
                report_date=report_date,
                source_id=str(path),
            )
        )

    for decision in DecisionStore().load_all():
        records.extend(extract_decision_memories(decision))

    for trade in TradeStore().load_all():
        memory = extract_trade_memory(trade)
        if memory is not None:
            records.append(memory)

    return records


def main():
    result = MemoryIngestionService().ingest_records(load_backfill_records())
    print(result.to_dict())


def _extract_run_id(report_markdown: str) -> str | None:
    match = RUN_ID_PATTERN.search(report_markdown)
    return match.group(1) if match else None


if __name__ == "__main__":
    main()
