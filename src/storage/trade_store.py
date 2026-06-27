import csv
from src.config import DATA_DIR
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

TRADES_FILE = DATA_DIR / "trades.csv"

TRADE_FIELDS = ["run_id", "date", "symbol", "action", "shares", "price", "total", "reasoning"]


class TradeStore:
    def save(self, trade: Trade) -> None:
        self._ensure_schema()
        file_exists = TRADES_FILE.exists() and TRADES_FILE.stat().st_size > 0
        with open(TRADES_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "run_id": trade.run_id or "",
                    "date": trade.date.isoformat(),
                    "symbol": trade.symbol,
                    "action": trade.action.value,
                    "shares": trade.shares,
                    "price": f"{trade.price:.2f}",
                    "total": f"{trade.total:.2f}",
                    "reasoning": trade.reasoning,
                }
            )
        logger.info("Saved trade: %s %s %s", trade.action.value, trade.shares, trade.symbol)

    def load_all(self) -> list[dict]:
        if not TRADES_FILE.exists():
            return []
        with open(TRADES_FILE, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _ensure_schema(self) -> None:
        if not TRADES_FILE.exists() or TRADES_FILE.stat().st_size == 0:
            return

        with open(TRADES_FILE, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == TRADE_FIELDS:
                return
            rows = list(reader)

        with open(TRADES_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in TRADE_FIELDS})
