import csv
from src.config import DATA_DIR
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

TRADES_FILE = DATA_DIR / "trades.csv"


class TradeStore:
    def save(self, trade: Trade) -> None:
        file_exists = TRADES_FILE.exists() and TRADES_FILE.stat().st_size > 0
        with open(TRADES_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["date", "symbol", "action", "shares", "price", "total", "reasoning"])
            writer.writerow([
                trade.date.isoformat(),
                trade.symbol,
                trade.action.value,
                trade.shares,
                f"{trade.price:.2f}",
                f"{trade.total:.2f}",
                trade.reasoning,
            ])
        logger.info("Saved trade: %s %s %s", trade.action.value, trade.shares, trade.symbol)

    def load_all(self) -> list[dict]:
        if not TRADES_FILE.exists():
            return []
        with open(TRADES_FILE, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
