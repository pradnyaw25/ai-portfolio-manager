from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TradeAction(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Trade:
    date: datetime
    symbol: str
    action: TradeAction
    shares: float
    price: float
    reasoning: str = ""
    run_id: str | None = None

    @property
    def total(self) -> float:
        return self.shares * self.price
