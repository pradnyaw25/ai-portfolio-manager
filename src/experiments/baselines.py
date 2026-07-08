"""Deterministic baselines for the fund-vs-baselines comparison (roadmap V1-1).

Each function turns a start capital + a price window into a :class:`VariantResult`
(a final value and a return). The live fund is scored the same way from its
recorded value history. Everything here is pure — prices in, result out — so the
numbers are reproducible and unit-testable; the CSV/price-fetch I/O lives in
``scripts/compare_baselines.py``.
"""

import random
from dataclasses import dataclass

# Fixed seed so the random baseline is reproducible run to run.
DEFAULT_SEED = 12345
DEFAULT_TRIALS = 500
DEFAULT_PICKS = 5


@dataclass
class VariantResult:
    name: str
    start_value: float
    end_value: float
    return_pct: float
    alpha_vs_spy: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "start_value": round(self.start_value, 2),
            "end_value": round(self.end_value, 2),
            "return_pct": round(self.return_pct, 6),
            "alpha_vs_spy": None if self.alpha_vs_spy is None else round(self.alpha_vs_spy, 6),
            "detail": self.detail,
        }


def fund_variant(start_value: float, end_value: float, name: str = "Glasshouse Fund") -> VariantResult:
    """Score the live fund from its recorded start/end portfolio value."""
    ret = (end_value / start_value - 1) if start_value else 0.0
    return VariantResult(name, start_value, end_value, ret, detail="the live AI fund")


def buy_and_hold(symbol: str, start_price: float, end_price: float, capital: float) -> VariantResult:
    """All capital into one symbol at the window start, held to the end."""
    ret = (end_price / start_price - 1) if start_price else 0.0
    return VariantResult(
        f"Buy & hold {symbol}", capital, capital * (1 + ret), ret, detail=f"100% {symbol} at inception"
    )


def random_from_watchlist(
    watchlist_prices: dict[str, tuple[float, float]],
    capital: float,
    *,
    picks: int = DEFAULT_PICKS,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
    name: str = "Random from watchlist",
) -> VariantResult:
    """The 'does the AI beat a monkey?' baseline: the MEAN return across many random
    equal-weight portfolios drawn from the watchlist — not one lucky/unlucky draw.

    ``watchlist_prices`` maps symbol -> (start_price, end_price).
    """
    eligible = sorted(s for s, (a, b) in watchlist_prices.items() if a and b and a > 0)
    if not eligible:
        return VariantResult(name, capital, capital, 0.0, detail="no usable prices")

    k = min(picks, len(eligible))
    rng = random.Random(seed)
    returns = []
    for _ in range(trials):
        chosen = rng.sample(eligible, k)
        # equal-weight portfolio return = mean of the per-name returns
        returns.append(sum(watchlist_prices[s][1] / watchlist_prices[s][0] - 1 for s in chosen) / k)

    mean_ret = sum(returns) / len(returns)
    return VariantResult(
        name,
        capital,
        capital * (1 + mean_ret),
        mean_ret,
        detail=f"mean of {trials} random {k}-name equal-weight portfolios",
    )


def with_alpha(variants: list[VariantResult], spy_return: float) -> list[VariantResult]:
    """Fill in each variant's alpha vs buy-and-hold SPY (excess return)."""
    for v in variants:
        v.alpha_vs_spy = v.return_pct - spy_return
    return variants
