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
            writer.writerow(self._row(trade))
        logger.info("Saved trade: %s %s %s", trade.action.value, trade.shares, trade.symbol)

    def save_run(self, run_id: str | None, trades: list[Trade]) -> None:
        """Idempotently persist all trades for a run.

        Replaces any rows already recorded for ``run_id`` with ``trades``, so
        re-running the same run_id produces no duplicates. Keyed on the run as a
        whole (not per symbol/action), which is collision-proof even when a run
        legitimately holds two trades for the same symbol/action (e.g. a PM buy
        plus a rebalance top-up). ``trades`` may be empty, which just clears any
        prior rows for the run.
        """
        self._ensure_schema()
        key = run_id or ""
        kept = [row for row in self.load_all() if row.get("run_id", "") != key]
        with open(TRADES_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
            writer.writeheader()
            for row in kept:
                writer.writerow({field: row.get(field, "") for field in TRADE_FIELDS})
            for trade in trades:
                writer.writerow(self._row(trade))
        logger.info("Saved %d trade(s) for run %s", len(trades), run_id or "(none)")

    @staticmethod
    def _row(trade: Trade) -> dict:
        return {
            "run_id": trade.run_id or "",
            "date": trade.date.isoformat(),
            "symbol": trade.symbol,
            "action": trade.action.value,
            "shares": trade.shares,
            "price": f"{trade.price:.2f}",
            "total": f"{trade.total:.2f}",
            "reasoning": trade.reasoning,
        }

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
