import csv
from datetime import date
from pathlib import Path

from src.config import DATA_DIR, BENCHMARK_SYMBOLS


class BenchmarkTracker:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "benchmark_history.csv"

    def record(self, market_data) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        existing_dates = self._existing_dates()
        today = date.today().isoformat()

        if today in existing_dates:
            return

        rows = []

        for symbol in BENCHMARK_SYMBOLS:
            price = market_data.get_price(symbol)
            rows.append({
                "date": today,
                "symbol": symbol,
                "price": price,
            })

        file_exists = self.path.exists()

        with self.path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "symbol", "price"])

            if not file_exists:
                writer.writeheader()

            writer.writerows(rows)

    def _existing_dates(self) -> set[str]:
        if not self.path.exists():
            return set()

        with self.path.open() as f:
            reader = csv.DictReader(f)
            return {row["date"] for row in reader}
