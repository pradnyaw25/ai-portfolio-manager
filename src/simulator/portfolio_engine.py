from datetime import date
from src.models.portfolio import PortfolioSnapshot, Position
from src.models.trade import Trade, TradeAction
from src.models.prediction import TradePrediction
from src.data_sources.market_data import MarketDataClient
from src.config import MAX_POSITION_SIZE
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PortfolioEngine:
    def __init__(self, initial_capital: float = 100000.0):
        self.cash = initial_capital
        self.positions: dict[str, Position] = {}

    @classmethod
    def from_portfolio(cls, snapshot: PortfolioSnapshot) -> "PortfolioEngine":
        engine = cls(initial_capital=0)
        engine.cash = snapshot.cash
        for p in snapshot.positions:
            engine.positions[p.symbol] = Position(
                symbol=p.symbol,
                shares=p.shares,
                avg_cost=p.avg_cost,
                current_price=p.current_price,
            )
        return engine

    def execute_trades(
        self, predictions: list[TradePrediction], market_data: MarketDataClient
    ) -> list[Trade]:
        executed = []
        for pred in predictions:
            if pred.action == "HOLD":
                continue
            try:
                price = market_data.get_price(pred.symbol)
                trade = self._execute_single(pred, price)
                if trade:
                    executed.append(trade)
            except Exception as e:
                logger.warning("Failed to execute trade for %s: %s", pred.symbol, e)
        return executed

    def _execute_single(self, pred: TradePrediction, price: float) -> Trade | None:
        if pred.action == "BUY":
            return self._buy(pred.symbol, pred.shares, price, pred.reasoning)
        elif pred.action == "SELL":
            return self._sell(pred.symbol, pred.shares, price, pred.reasoning)
        return None

    def _buy(self, symbol: str, shares: int, price: float, reasoning: str) -> Trade | None:
        cost = shares * price
        total_value = self.cash + sum(p.market_value for p in self.positions.values())
        if cost > total_value * MAX_POSITION_SIZE:
            shares = int((total_value * MAX_POSITION_SIZE) / price)
            cost = shares * price
        if cost > self.cash or shares <= 0:
            logger.info("Insufficient funds to buy %s", symbol)
            return None

        self.cash -= cost
        if symbol in self.positions:
            pos = self.positions[symbol]
            total_shares = pos.shares + shares
            pos.avg_cost = (pos.cost_basis + cost) / total_shares
            pos.shares = total_shares
        else:
            self.positions[symbol] = Position(
                symbol=symbol, shares=shares, avg_cost=price, current_price=price
            )
        self.positions[symbol].current_price = price

        return Trade(
            date=date.today(),
            symbol=symbol,
            action=TradeAction.BUY,
            shares=shares,
            price=price,
            reasoning=reasoning,
        )

    def _sell(self, symbol: str, shares: int, price: float, reasoning: str) -> Trade | None:
        if symbol not in self.positions:
            logger.info("No position in %s to sell", symbol)
            return None

        pos = self.positions[symbol]
        shares = min(shares, int(pos.shares))
        if shares <= 0:
            return None

        self.cash += shares * price
        pos.shares -= shares
        pos.current_price = price

        if pos.shares <= 0:
            del self.positions[symbol]

        return Trade(
            date=date.today(),
            symbol=symbol,
            action=TradeAction.SELL,
            shares=shares,
            price=price,
            reasoning=reasoning,
        )

    def get_holdings(self) -> list[Position]:
        return list(self.positions.values())

    def get_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            date=date.today(),
            cash=self.cash,
            positions=list(self.positions.values()),
        )
    def mark_to_market(self, market_data: MarketDataClient) -> None:
        for symbol, position in self.positions.items():
            try:
                new_price = market_data.get_price(symbol)
                if new_price is None or new_price <= 0:
                    logger.warning("Invalid price for %s: %s — skipping", symbol, new_price)
                    continue
                old_price = position.current_price
                position.current_price = new_price
                logger.info(
                    "Mark-to-market %s: avg=$%.2f old=$%.2f new=$%.2f",
                    symbol, position.avg_cost, old_price, new_price,
                )
            except Exception as e:
                logger.warning("Failed to update price for %s: %s", symbol, e)
