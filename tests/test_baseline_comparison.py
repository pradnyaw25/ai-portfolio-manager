"""build_comparison: assemble the fund-vs-baselines payload from history + prices."""

import pytest
import pandas as pd

from src.experiments.comparison import build_comparison


class _FakeMarketData:
    """get_history returns a 2-row Close frame implying `ret`, or None (no history)."""

    def __init__(self, ret):
        self._ret = ret

    def get_history(self, symbol, days):
        if self._ret is None:
            return None
        return pd.DataFrame({"Close": [100.0, 100.0 * (1 + self._ret)]})


def _write_history(tmp_path):
    (tmp_path / "portfolio_history.csv").write_text(
        "date,total_value\n2026-06-11,1000000\n2026-07-07,1030000\n"
    )
    (tmp_path / "benchmark_history.csv").write_text(
        "date,symbol,price\n"
        "2026-06-11,SPY,100\n2026-07-07,SPY,110\n"
        "2026-06-11,QQQ,200\n2026-07-07,QQQ,190\n"
    )


def test_build_comparison_scores_fund_and_baselines(tmp_path):
    _write_history(tmp_path)
    payload = build_comparison(_FakeMarketData(0.05), trials=50, data_dir=tmp_path)

    by_name = {v["name"]: v for v in payload["variants"]}
    assert payload["start_date"] == "2026-06-11" and payload["end_date"] == "2026-07-07"
    assert round(by_name["Glasshouse Fund"]["return_pct"], 4) == 0.03   # 1.03M / 1.00M
    assert round(by_name["Buy & hold SPY"]["return_pct"], 4) == 0.10    # 100 -> 110
    assert round(by_name["Buy & hold QQQ"]["return_pct"], 4) == -0.05   # 200 -> 190
    # every watchlist name moved +5%, so any random portfolio returns +5%
    assert round(by_name["Random from watchlist"]["return_pct"], 4) == 0.05
    # alpha vs SPY (+10%): fund 3% - 10% = -7%
    assert round(by_name["Glasshouse Fund"]["alpha_vs_spy"], 4) == -0.07


def test_random_baseline_omitted_when_no_prices(tmp_path):
    _write_history(tmp_path)
    payload = build_comparison(_FakeMarketData(None), data_dir=tmp_path)  # no history for any name
    names = [v["name"] for v in payload["variants"]]
    assert "Random from watchlist" not in names  # omitted, not a misleading 0.00%
    assert "Glasshouse Fund" in names and "Buy & hold SPY" in names


def test_build_comparison_needs_two_days(tmp_path):
    (tmp_path / "portfolio_history.csv").write_text("date,total_value\n2026-06-11,1000000\n")
    with pytest.raises(ValueError):
        build_comparison(_FakeMarketData(0.05), data_dir=tmp_path)
