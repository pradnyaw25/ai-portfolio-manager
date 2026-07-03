import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from src.config import DATA_DIR
from src.models.portfolio import PortfolioSnapshot
from src.models.prediction import TradePrediction
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

DECISIONS_FILE = DATA_DIR / "decisions.jsonl"


class DecisionStore:
    """Append-only journal of each daily LLM decision and risk review."""

    def save(
        self,
        *,
        portfolio: PortfolioSnapshot,
        raw_decision: dict[str, Any],
        approved: list[TradePrediction],
        rejected: list[Any],
        executed: list[Trade],
        cash_thesis: str | None = None,
        rebalance_trades: list[TradePrediction] | None = None,
        memory_used: list[dict] | None = None,
        memory_status: str = "not_recorded",
        memory_error: str | None = None,
        memory_citations: list[dict] | None = None,
        memory_citation_warnings: list[str] | None = None,
        grounding: dict | None = None,
        research_brief: dict | None = None,
        run_id: str | None = None,
    ) -> None:
        row = {
            "run_id": run_id,
            "date": date.today().isoformat(),
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "portfolio": {
                "total_value": portfolio.total_value,
                "cash": portfolio.cash,
                "cash_pct": portfolio.cash_pct,
                "positions": len(portfolio.positions),
            },
            "raw_decision": raw_decision,
            "approved_trades": approved,
            "rejected_trades": rejected,
            "executed_trades": executed,
            "cash_thesis": cash_thesis,
            "rebalance_trades": rebalance_trades or [],
            "memory_used": memory_used or [],
            "memory_status": memory_status,
            "memory_error": memory_error,
            "memory_citations": memory_citations or [],
            "memory_citation_warnings": memory_citation_warnings or [],
            "grounding": grounding,
            "research_brief": research_brief,
        }
        self._upsert(row, run_id)
        logger.info("Saved decision journal entry")

    def _upsert(self, row: dict[str, Any], run_id: str | None) -> None:
        """Write ``row``, replacing any existing entry with the same run_id.

        One decision per run: re-running a run_id overwrites its journal entry
        instead of appending a duplicate. Entries without a run_id (legacy rows)
        are always kept and this row is appended.
        """
        rows = self.load_all()
        if run_id is not None:
            rows = [r for r in rows if r.get("run_id") != run_id]
        rows.append(row)
        with open(DECISIONS_FILE, "w") as f:
            for entry in rows:
                f.write(json.dumps(entry, default=self._json_default) + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        if not DECISIONS_FILE.exists():
            return []
        return [json.loads(line) for line in DECISIONS_FILE.read_text().splitlines() if line.strip()]

    def _json_default(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if is_dataclass(obj):
            return asdict(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
