"""Fund-vs-baselines comparison math (roadmap V1-1)."""

from src.experiments.baselines import (
    buy_and_hold,
    fund_variant,
    random_from_watchlist,
    with_alpha,
)


def test_fund_variant_return():
    v = fund_variant(1_000_000, 1_029_000)
    assert round(v.return_pct, 4) == 0.029
    assert v.end_value == 1_029_000


def test_buy_and_hold_scales_capital_by_price_move():
    v = buy_and_hold("SPY", 100.0, 110.0, 1_000_000)
    assert round(v.return_pct, 4) == 0.10
    assert v.end_value == 1_100_000
    assert "SPY" in v.name


def test_random_baseline_is_mean_and_reproducible():
    # Two names: +20% and -10%. Any 1-name portfolio is one of them; the mean over
    # many draws converges near the average of the eligible names.
    prices = {"AAA": (100.0, 120.0), "BBB": (100.0, 90.0)}
    a = random_from_watchlist(prices, 1_000_000, picks=1, trials=1000, seed=7)
    b = random_from_watchlist(prices, 1_000_000, picks=1, trials=1000, seed=7)
    assert a.return_pct == b.return_pct  # same seed -> reproducible
    assert -0.10 < a.return_pct < 0.20  # bounded by the two names' returns
    # a 2-name equal-weight portfolio is deterministic: mean of +20% and -10% = +5%
    both = random_from_watchlist(prices, 1_000_000, picks=2, trials=50, seed=1)
    assert round(both.return_pct, 4) == 0.05


def test_random_baseline_handles_no_prices():
    v = random_from_watchlist({}, 1_000_000)
    assert v.return_pct == 0.0
    assert v.end_value == 1_000_000


def test_with_alpha_subtracts_spy_return():
    variants = [fund_variant(100, 110), buy_and_hold("SPY", 100, 105, 100)]
    with_alpha(variants, spy_return=0.05)
    assert round(variants[0].alpha_vs_spy, 4) == 0.05  # fund +10% - SPY +5%
    assert round(variants[1].alpha_vs_spy, 4) == 0.0  # SPY vs itself
