from datetime import date
from src.simulator.portfolio_engine import PortfolioEngine
from src.models.prediction import TradePrediction
from src.models.portfolio import PortfolioSnapshot, Position


class FakeMarketData:
    def __init__(self, prices: dict[str, float]):
        self._prices = prices

    def get_price(self, symbol: str) -> float:
        return self._prices[symbol]


def test_initial_state():
    engine = PortfolioEngine(initial_capital=100000)
    snapshot = engine.get_snapshot()
    assert snapshot.cash == 100000
    assert snapshot.total_value == 100000
    assert len(snapshot.positions) == 0


def test_buy_trade():
    engine = PortfolioEngine(initial_capital=100000)
    market = FakeMarketData({"AAPL": 150.0})
    predictions = [TradePrediction(symbol="AAPL", action="BUY", shares=10, confidence=0.9, reasoning="test")]

    trades = engine.execute_trades(predictions, market)

    assert len(trades) == 1
    assert trades[0].symbol == "AAPL"
    assert trades[0].shares == 10
    assert engine.cash == 100000 - (10 * 150)
    assert "AAPL" in engine.positions
    assert engine.positions["AAPL"].shares == 10


def test_sell_trade():
    engine = PortfolioEngine(initial_capital=100000)
    engine.positions["AAPL"] = Position(symbol="AAPL", shares=20, avg_cost=140.0, current_price=150.0)
    engine.cash = 100000 - (20 * 140)
    market = FakeMarketData({"AAPL": 160.0})
    predictions = [TradePrediction(symbol="AAPL", action="SELL", shares=10, confidence=0.8, reasoning="take profit")]

    trades = engine.execute_trades(predictions, market)

    assert len(trades) == 1
    assert engine.positions["AAPL"].shares == 10
    assert engine.cash == (100000 - 20 * 140) + (10 * 160)


def test_sell_all_removes_position():
    engine = PortfolioEngine(initial_capital=100000)
    engine.positions["TSLA"] = Position(symbol="TSLA", shares=5, avg_cost=200.0, current_price=200.0)
    market = FakeMarketData({"TSLA": 210.0})
    predictions = [TradePrediction(symbol="TSLA", action="SELL", shares=5, confidence=0.9, reasoning="exit")]

    engine.execute_trades(predictions, market)

    assert "TSLA" not in engine.positions


def test_buy_respects_max_position_size():
    engine = PortfolioEngine(initial_capital=10000)
    market = FakeMarketData({"AAPL": 150.0})
    predictions = [TradePrediction(symbol="AAPL", action="BUY", shares=100, confidence=0.9, reasoning="test")]

    trades = engine.execute_trades(predictions, market)

    if trades:
        position_value = engine.positions["AAPL"].market_value
        assert position_value <= 10000 * 0.10 + 150


def test_cannot_sell_unowned_stock():
    engine = PortfolioEngine(initial_capital=100000)
    market = FakeMarketData({"AAPL": 150.0})
    predictions = [TradePrediction(symbol="AAPL", action="SELL", shares=10, confidence=0.9, reasoning="test")]

    trades = engine.execute_trades(predictions, market)

    assert len(trades) == 0


def test_from_portfolio():
    snapshot = PortfolioSnapshot(
        date=date.today(),
        cash=50000,
        positions=[Position(symbol="MSFT", shares=10, avg_cost=300.0, current_price=310.0)],
    )
    engine = PortfolioEngine.from_portfolio(snapshot)

    assert engine.cash == 50000
    assert "MSFT" in engine.positions
    assert engine.positions["MSFT"].shares == 10
