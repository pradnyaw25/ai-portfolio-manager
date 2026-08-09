"""Rate limits must not turn into a quietly wrong decision.

Both data sources used to catch every exception and return an empty result, so a 429
was indistinguishable from a delisted ticker. The fund would decide on whatever
partial data arrived and journal a normal-looking day. Nothing downstream catches
that: the run ran, and it succeeded — so #92's exit code and the run-health watchdog
both see a healthy day.
"""

import pytest

from src.data_sources.market_data import MarketDataClient, MarketDataUnavailable


class _Boom(Exception):
    """Stands in for a 429 / connection reset out of yfinance."""


def _client(monkeypatch, price_impl, *, max_retries=3):
    slept = []
    client = MarketDataClient(max_retries=max_retries, sleep=slept.append)
    monkeypatch.setattr(client, "get_price", price_impl)
    return client, slept


# --- retries ---------------------------------------------------------------


def test_a_transient_error_is_retried_and_can_succeed():
    calls = {"n": 0}
    slept = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom("429 Too Many Requests")
        return "ok"

    client = MarketDataClient(max_retries=3, sleep=slept.append)

    assert client._with_retries(flaky, "test fetch") == "ok"
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]  # exponential, and it actually backed off


def test_retries_are_bounded_and_then_the_error_surfaces():
    slept = []
    client = MarketDataClient(max_retries=2, sleep=slept.append)

    with pytest.raises(_Boom):
        client._with_retries(lambda: (_ for _ in ()).throw(_Boom("429")), "test fetch")

    assert len(slept) == 2  # max_retries backoffs, then give up


def test_an_empty_result_is_data_not_a_failure():
    """A delisted ticker returns an empty frame rather than raising. Retrying that
    just burns three round-trips to reach the same answer."""
    calls = {"n": 0}

    def empty():
        calls["n"] += 1
        return []

    client = MarketDataClient(max_retries=3, sleep=lambda _: None)

    assert client._with_retries(empty, "test fetch") == []
    assert calls["n"] == 1  # not retried


# --- the missing-data ceiling ----------------------------------------------


def test_a_few_missing_symbols_are_tolerated(monkeypatch):
    """One delisted name out of twenty should not stop the fund trading."""
    def price(symbol):
        if symbol == "DEAD":
            raise ValueError("No price data for DEAD")
        return 100.0

    client, _ = _client(monkeypatch, price)
    symbols = [f"S{i}" for i in range(19)] + ["DEAD"]

    prices = client.get_prices(symbols)

    assert len(prices) == 19
    assert "DEAD" not in prices


def test_losing_most_of_the_universe_raises(monkeypatch):
    """The 429 case. Deciding on a third of the universe is not a decision."""
    def price(symbol):
        if symbol in {"AAPL", "MSFT"}:
            return 100.0
        raise _Boom("429 Too Many Requests")

    client, _ = _client(monkeypatch, price)

    with pytest.raises(MarketDataUnavailable) as exc:
        client.get_prices(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"])

    # The message must name what went missing, or the failure is unactionable.
    assert "2/6" in str(exc.value)
    assert "GOOGL" in str(exc.value)


def test_a_total_outage_raises_rather_than_returning_nothing(monkeypatch):
    client, _ = _client(monkeypatch, lambda s: (_ for _ in ()).throw(_Boom("429")))

    with pytest.raises(MarketDataUnavailable):
        client.get_prices(["AAPL", "MSFT", "GOOGL"])


def test_an_empty_request_is_not_an_outage(monkeypatch):
    client, _ = _client(monkeypatch, lambda s: 100.0)

    assert client.get_prices([]) == {}


def test_a_fully_successful_batch_is_unchanged(monkeypatch):
    client, _ = _client(monkeypatch, lambda s: 100.0)

    assert client.get_prices(["AAPL", "MSFT"]) == {"AAPL": 100.0, "MSFT": 100.0}
