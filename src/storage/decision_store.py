import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
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
    ) -> None:
        row = {
            "date": date.today().isoformat(),
            "created_at": datetime.utcnow().isoformat() + "Z",
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
        }
        with open(DECISIONS_FILE, "a") as f:
            f.write(json.dumps(row, default=self._json_default) + "\n")
        logger.info("Saved decision journal entry")

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
