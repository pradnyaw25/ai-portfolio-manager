from datetime import date, timedelta
import yfinance as yf
from src.utils.logger import get_logger

logger = get_logger(__name__)

BENCHMARKS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
}


class BenchmarkClient:
    def get_sp500_performance(self, days: int = 30) -> dict:
        return self.get_benchmark_performance("sp500", days)

    def get_benchmark_performance(self, name: str, days: int = 30) -> dict:
        symbol = BENCHMARKS.get(name)
        if not symbol:
            raise ValueError(f"Unknown benchmark: {name}")

        end = date.today()
        start = end - timedelta(days=days)
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat())

        if hist.empty:
            return {"name": name, "return_pct": 0.0, "current": 0.0}

        start_price = float(hist["Close"].iloc[0])
        end_price = float(hist["Close"].iloc[-1])
        return_pct = (end_price / start_price) - 1

        return {
            "name": name,
            "symbol": symbol,
            "return_pct": return_pct,
            "current": end_price,
            "start_price": start_price,
            "days": days,
        }

    def get_all_benchmarks(self, days: int = 30) -> list[dict]:
        results = []
        for name in BENCHMARKS:
            try:
                results.append(self.get_benchmark_performance(name, days))
            except Exception as e:
                logger.warning("Failed to get benchmark %s: %s", name, e)
        return results
