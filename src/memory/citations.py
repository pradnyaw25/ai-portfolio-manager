from dataclasses import dataclass, field
from typing import Any

MEMORY_ID_PREFIXES = (
    "thesis:",
    "risk_lesson:",
    "trade:",
    "report_summary:",
    "macro:",
    "macro_regime:",
    "mistake:",
    "earnings_event:",
)


@dataclass
class MemoryCitation:
    memory_id: str
    citation_type: str
    source_field: str
    trade_symbol: str | None = None
    trade_action: str | None = None
    memory_type: str | None = None
    date: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    symbols: list[str] = field(default_factory=list)


@dataclass
class MemoryCitationReview:
    citations: list[MemoryCitation]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "citations": [
                {
                    "memory_id": citation.memory_id,
                    "citation_type": citation.citation_type,
                    "source_field": citation.source_field,
                    "trade_symbol": citation.trade_symbol,
                    "trade_action": citation.trade_action,
                    "memory_type": citation.memory_type,
                    "date": citation.date,
                    "source_type": citation.source_type,
                    "source_id": citation.source_id,
                    "symbols": citation.symbols,
                }
                for citation in self.citations
            ],
            "warnings": self.warnings,
        }


def review_memory_citations(
    *,
    raw_decision: dict[str, Any],
    memory_used: list[dict],
) -> MemoryCitationReview:
    memory_index = _index_memory(memory_used)
    citations: list[MemoryCitation] = []
    warnings: list[str] = []
    seen = set()

    for trade in raw_decision.get("trades", []) or []:
        trade_symbol = str(trade.get("symbol", "")).upper() or None
        trade_action = str(trade.get("action", "")).upper() or None
        for source in _as_list(trade.get("sources_used")):
            source_text = str(source).strip()
            if not _looks_like_memory_id(source_text):
                continue
            if source_text not in memory_index:
                warnings.append(
                    f"Trade {trade_symbol or 'UNKNOWN'} cited unknown memory id: {source_text}"
                )
                continue
            citation_key = ("trade", trade_symbol, trade_action, source_text)
            if citation_key in seen:
                continue
            seen.add(citation_key)
            citations.append(
                _build_citation(
                    memory_id=source_text,
                    memory=memory_index[source_text],
                    citation_type="trade",
                    source_field="trades.sources_used",
                    trade_symbol=trade_symbol,
                    trade_action=trade_action,
                )
            )

    for source in _as_list(raw_decision.get("sources_used")):
        source_text = str(source).strip()
        if not _looks_like_memory_id(source_text):
            continue
        if source_text not in memory_index:
            warnings.append(f"Decision cited unknown memory id: {source_text}")
            continue
        citation_key = ("decision", source_text)
        if citation_key in seen:
            continue
        seen.add(citation_key)
        citations.append(
            _build_citation(
                memory_id=source_text,
                memory=memory_index[source_text],
                citation_type="decision",
                source_field="sources_used",
            )
        )

    return MemoryCitationReview(citations=citations, warnings=warnings)


def _build_citation(
    *,
    memory_id: str,
    memory: dict,
    citation_type: str,
    source_field: str,
    trade_symbol: str | None = None,
    trade_action: str | None = None,
) -> MemoryCitation:
    metadata = memory.get("metadata") or {}
    return MemoryCitation(
        memory_id=memory_id,
        citation_type=citation_type,
        source_field=source_field,
        trade_symbol=trade_symbol,
        trade_action=trade_action,
        memory_type=memory.get("type") or metadata.get("memory_type") or metadata.get("type"),
        date=memory.get("date") or metadata.get("date"),
        source_type=memory.get("source_type") or metadata.get("source_type"),
        source_id=memory.get("source_id") or metadata.get("source_id"),
        symbols=memory.get("symbols") or metadata.get("symbols") or [],
    )


def _index_memory(memory_used: list[dict]) -> dict[str, dict]:
    indexed = {}
    for memory in memory_used:
        memory_id = memory.get("id") or (memory.get("metadata") or {}).get("id")
        if memory_id:
            indexed[str(memory_id)] = memory
    return indexed


def _looks_like_memory_id(value: str) -> bool:
    return value.startswith(MEMORY_ID_PREFIXES)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
