from dataclasses import dataclass, field
from enum import Enum


class Outlook(Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


@dataclass
class TradePrediction:
    symbol: str
    action: str
    shares: int
    confidence: float
    reasoning: str
    # "llm" for model-proposed trades; "system" for deterministic risk-engine
    # exits (stop-loss / take-profit).
    origin: str = "llm"


@dataclass
class PortfolioDecision:
    reasoning: str
    trades: list[TradePrediction] = field(default_factory=list)
    outlook: Outlook = Outlook.NEUTRAL
    risk_assessment: str = ""
