from datetime import date, timedelta
import yfinance as yf
import pandas as pd
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketDataClient:
    def get_price(self, symbol: str) -> float:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if hist.empty:
            raise ValueError(f"No price data for {symbol}")
        return float(hist["Close"].iloc[-1])

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        prices = {}
        for symbol in symbols:
            try:
                prices[symbol] = self.get_price(symbol)
            except Exception as e:
                logger.warning("Failed to get price for %s: %s", symbol, e)
        return prices

    def get_history(
        self, symbol: str, days: int = 30
    ) -> pd.DataFrame:
        end = date.today()
        start = end - timedelta(days=days)
        ticker = yf.Ticker(symbol)
        return ticker.history(start=start.isoformat(), end=end.isoformat())

    def get_top_movers(self, symbols: list[str], days: int = 5) -> list[dict]:
        movers = []
        for symbol in symbols:
            try:
                hist = self.get_history(symbol, days=days)
                if len(hist) < 2:
                    continue
                change = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1
                movers.append({"symbol": symbol, "change_pct": change})
            except Exception as e:
                logger.warning("Failed to get history for %s: %s", symbol, e)
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return movers
