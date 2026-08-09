"""Market data access, with retries and a loud failure when too much is missing.

Every method here used to catch bare ``Exception``, log a warning and return an empty
result. That made a rate limit indistinguishable from a delisted ticker: on a 429 the
fund would quietly decide on whatever subset of prices happened to arrive, journal a
normal-looking day, and report success. The run-health watchdog cannot catch it either
— the run *did* run, and it *did* succeed.

Two changes fix that:

* **Retries.** A raised exception is a transport problem (rate limit, connection drop,
  provider hiccup) and is retried with exponential backoff. An *empty result* is not —
  yfinance returns an empty frame for a symbol that genuinely has no data, so that
  path returns None immediately rather than burning retries on a delisted ticker.
* **A missing-data ceiling.** Losing one name out of thirty is survivable. Losing a
  third of the universe is not a portfolio decision worth publishing, so it raises and
  lets the run fail visibly.
"""

import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from src.config import MARKET_DATA_MAX_MISSING_PCT, MARKET_DATA_MAX_RETRIES
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketDataUnavailable(RuntimeError):
    """Raised when too much of a requested batch could not be fetched."""


class MarketDataClient:
    def __init__(self, *, max_retries: int | None = None, sleep=time.sleep):
        # sleep is injectable so tests exercise the retry path without real delays.
        self._max_retries = (
            MARKET_DATA_MAX_RETRIES if max_retries is None else max_retries
        )
        self._sleep = sleep

    def _with_retries(self, fetch, what: str):
        """Run ``fetch``, retrying raised errors with exponential backoff.

        Returns the result, or raises the final error. A fetch that *returns*
        something (including an empty frame) is never retried — that is data, not a
        failure.
        """
        attempt = 0
        while True:
            try:
                return fetch()
            except Exception as exc:  # noqa: BLE001 — yfinance raises many types
                if attempt >= self._max_retries:
                    logger.error(
                        "%s failed after %d attempts: %s",
                        what,
                        attempt + 1,
                        str(exc)[:200],
                    )
                    raise
                delay = 2.0**attempt
                logger.warning(
                    "%s error (attempt %d/%d), backing off %.1fs: %s",
                    what,
                    attempt + 1,
                    self._max_retries + 1,
                    delay,
                    str(exc)[:150],
                )
                self._sleep(delay)
                attempt += 1

    def get_price(self, symbol: str) -> float:
        hist = self._with_retries(
            lambda: yf.Ticker(symbol).history(period="1d"), f"price fetch for {symbol}"
        )
        if hist.empty:
            raise ValueError(f"No price data for {symbol}")
        return float(hist["Close"].iloc[-1])

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """Fetch prices for a batch, tolerating a few gaps but not a collapse."""
        prices: dict[str, float] = {}
        failed: list[str] = []
        for symbol in symbols:
            try:
                prices[symbol] = self.get_price(symbol)
            except Exception as exc:  # noqa: BLE001
                failed.append(symbol)
                logger.warning("Failed to get price for %s: %s", symbol, exc)

        if failed and symbols:
            missing_pct = len(failed) / len(symbols)
            logger.warning(
                "Priced %d/%d symbols (%.0f%% missing): %s",
                len(prices),
                len(symbols),
                missing_pct * 100,
                ", ".join(sorted(failed)),
            )
            # A decision made on a fraction of the universe is not a decision. Fail
            # loudly instead of journalling a normal-looking day built on gaps.
            if missing_pct > MARKET_DATA_MAX_MISSING_PCT:
                raise MarketDataUnavailable(
                    f"only {len(prices)}/{len(symbols)} symbols priced "
                    f"({missing_pct:.0%} missing, ceiling is "
                    f"{MARKET_DATA_MAX_MISSING_PCT:.0%}) — refusing to decide on "
                    f"partial market data. Missing: {', '.join(sorted(failed))}"
                )
        return prices

    def get_history(self, symbol: str, days: int = 30) -> pd.DataFrame:
        end = date.today()
        start = end - timedelta(days=days)
        return self._with_retries(
            lambda: yf.Ticker(symbol).history(
                start=start.isoformat(), end=end.isoformat()
            ),
            f"history fetch for {symbol}",
        )

    def get_top_movers(self, symbols: list[str], days: int = 5) -> list[dict]:
        movers = []
        for symbol in symbols:
            try:
                hist = self.get_history(symbol, days=days)
                if len(hist) < 2:
                    continue
                change = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1
                movers.append({"symbol": symbol, "change_pct": change})
            except Exception as e:  # noqa: BLE001 — one bad name must not stop the scan
                logger.warning("Failed to get history for %s: %s", symbol, e)
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return movers
