import hashlib
from datetime import date
from typing import Any

from src.memory.schemas import MemoryRecord


def extract_report_memories(
    *,
    report_markdown: str,
    run_id: str,
    report_date: str | None = None,
    source_id: str | None = None,
) -> list[MemoryRecord]:
    if not report_markdown.strip():
        return []

    memory_date = report_date or date.today().isoformat()
    source = source_id or f"report:{memory_date}"
    records = [
        MemoryRecord(
            id=f"report_summary:{run_id}",
            memory_type="report_summary",
            content=_compact(report_markdown),
            date=memory_date,
            run_id=run_id,
            source_type="daily_report",
            source_id=source,
        )
    ]

    analysis = _section(report_markdown, "Analysis")
    if analysis:
        records.append(
            MemoryRecord(
                id=f"thesis:{run_id}:report_analysis",
                memory_type="thesis",
                content=analysis,
                date=memory_date,
                run_id=run_id,
                source_type="daily_report",
                source_id=source,
                metadata={"section": "Analysis"},
            )
        )

    risk_assessment = _section(report_markdown, "Risk Assessment")
    if risk_assessment:
        records.append(
            MemoryRecord(
                id=f"risk_lesson:{run_id}:report_risk",
                memory_type="risk_lesson",
                content=risk_assessment,
                date=memory_date,
                run_id=run_id,
                source_type="daily_report",
                source_id=source,
                metadata={"section": "Risk Assessment"},
            )
        )

    return records


def extract_decision_memories(decision: dict[str, Any]) -> list[MemoryRecord]:
    run_id = decision.get("run_id") or _stable_hash(str(decision))
    decision_date = decision.get("date") or date.today().isoformat()
    source_id = f"decision:{run_id}"
    raw_decision = decision.get("raw_decision") or {}
    records: list[MemoryRecord] = []

    summary = raw_decision.get("summary")
    if summary:
        records.append(
            MemoryRecord(
                id=f"thesis:{run_id}:decision_summary",
                memory_type="thesis",
                content=str(summary).strip(),
                date=decision_date,
                run_id=decision.get("run_id"),
                source_type="decision",
                source_id=source_id,
                metadata={"outlook": raw_decision.get("outlook")},
            )
        )

    cash_thesis = decision.get("cash_thesis")
    if cash_thesis:
        records.append(
            MemoryRecord(
                id=f"risk_lesson:{run_id}:cash_thesis",
                memory_type="risk_lesson",
                content=str(cash_thesis).strip(),
                date=decision_date,
                run_id=decision.get("run_id"),
                source_type="decision",
                source_id=source_id,
                metadata={"topic": "cash_thesis"},
            )
        )

    for index, rejected in enumerate(decision.get("rejected_trades") or []):
        symbol = str(rejected.get("symbol", "")).upper().strip()
        reason = str(rejected.get("reason", "")).strip()
        action = str(rejected.get("action", "")).upper().strip()
        if not symbol and not reason:
            continue
        records.append(
            MemoryRecord(
                id=f"risk_lesson:{run_id}:rejected:{index}:{symbol or 'unknown'}",
                memory_type="risk_lesson",
                content=f"Rejected {action or 'trade'} {symbol or 'UNKNOWN'}: {reason}",
                date=decision_date,
                run_id=decision.get("run_id"),
                symbols=[symbol] if symbol else [],
                source_type="decision",
                source_id=source_id,
                metadata={"action": action, "reason": reason},
            )
        )

    return records


def extract_trade_memory(trade: dict[str, Any]) -> MemoryRecord | None:
    run_id = trade.get("run_id") or None
    trade_date = trade.get("date") or date.today().isoformat()
    symbol = str(trade.get("symbol", "")).upper().strip()
    action = str(trade.get("action", "")).upper().strip()
    reasoning = str(trade.get("reasoning", "")).strip()
    if not symbol or not action:
        return None

    source_id = f"trade:{run_id or trade_date}:{symbol}:{action}"
    content = f"{action} {trade.get('shares', '')} {symbol} at {trade.get('price', '')}."
    if reasoning:
        content = f"{content} Thesis: {reasoning}"

    return MemoryRecord(
        id=f"trade:{run_id or _stable_hash(str(trade))}:{symbol}:{action}",
        memory_type="trade",
        content=content,
        date=trade_date,
        run_id=run_id,
        symbols=[symbol],
        source_type="trade",
        source_id=source_id,
        metadata={
            "action": action,
            "shares": trade.get("shares"),
            "price": trade.get("price"),
            "total": trade.get("total"),
        },
    )


def _section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index + 1
            break
    if start is None:
        return ""

    section_lines = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section_lines.append(line)
    return _compact("\n".join(section_lines))


def _compact(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
