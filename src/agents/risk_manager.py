from dataclasses import dataclass, field
from typing import Any

from src.config import (
    MAX_DAILY_TURNOVER,
    MAX_SECTOR_CONCENTRATION,
    MIN_TRADE_CONFIDENCE,
    sector_for,
)
from src.models.portfolio import PortfolioSnapshot
from src.models.prediction import TradePrediction
from src.utils.logger import get_logger

logger = get_logger(__name__)

VALID_ACTIONS = {"BUY", "SELL", "HOLD"}


@dataclass
class RejectedTrade:
    symbol: str
    action: str
    shares: int
    reason: str


@dataclass
class RiskReview:
    approved: list[TradePrediction]
    rejected: list[RejectedTrade]
    risk_events: list[dict] = field(default_factory=list)


class RiskManagerAgent:
    """Deterministic guardrail layer between the LLM and the simulator.

    The portfolio manager can be creative. This class should be boring:
    normalize the LLM output, reject malformed/low-confidence trades, and cap
    total daily turnover before orders reach the execution engine.
    """

    def review(
        self,
        raw_trades: list[dict[str, Any]],
        portfolio: PortfolioSnapshot,
        prices: dict[str, float],
        turnover_override: float | None = None,
    ) -> RiskReview:
        approved: list[TradePrediction] = []
        rejected: list[RejectedTrade] = []
        turnover_pct = turnover_override if turnover_override is not None else MAX_DAILY_TURNOVER
        remaining_turnover = portfolio.total_value * turnover_pct
        sector_exposure = self._sector_exposure(portfolio)
        sector_limit = portfolio.total_value * MAX_SECTOR_CONCENTRATION

        for raw in raw_trades:
            symbol = str(raw.get("symbol", "")).upper().strip()
            action = str(raw.get("action", "")).upper().strip()
            shares = self._parse_int(raw.get("shares", 0))
            confidence = self._parse_float(raw.get("confidence", 0.5))
            reasoning = str(raw.get("reason", raw.get("reasoning", ""))).strip()
            origin = str(raw.get("origin", "llm")).strip() or "llm"

            base_rejection = self._base_rejection_reason(
                symbol=symbol,
                action=action,
                shares=shares,
                confidence=confidence,
                prices=prices,
            )
            if base_rejection:
                rejected.append(RejectedTrade(symbol, action, shares, base_rejection))
                continue

            if action == "HOLD":
                continue

            price = prices[symbol]
            sector = sector_for(symbol)
            requested_value = shares * price
            if requested_value > remaining_turnover:
                capped_shares = int(remaining_turnover / price)
                if capped_shares <= 0:
                    rejected.append(
                        RejectedTrade(symbol, action, shares, "daily turnover limit already reached")
                    )
                    continue
                logger.info(
                    "Capped %s %s from %s shares to %s shares due to daily turnover limit",
                    action,
                    symbol,
                    shares,
                    capped_shares,
                )
                shares = capped_shares
                requested_value = shares * price

            # Sector-concentration cap applies only to BUYs (SELLs reduce exposure).
            if action == "BUY":
                available = sector_limit - sector_exposure.get(sector, 0.0)
                if available <= 0:
                    rejected.append(
                        RejectedTrade(
                            symbol, action, shares,
                            f"{sector} sector concentration limit "
                            f"({MAX_SECTOR_CONCENTRATION:.0%}) reached",
                        )
                    )
                    continue
                if requested_value > available:
                    capped_shares = int(available / price)
                    if capped_shares <= 0:
                        rejected.append(
                            RejectedTrade(
                                symbol, action, shares,
                                f"{sector} sector concentration limit "
                                f"({MAX_SECTOR_CONCENTRATION:.0%}) reached",
                            )
                        )
                        continue
                    logger.info(
                        "Capped BUY %s from %s to %s shares due to %s sector limit",
                        symbol, shares, capped_shares, sector,
                    )
                    shares = capped_shares
                    requested_value = shares * price

            remaining_turnover -= requested_value
            if action == "BUY":
                sector_exposure[sector] = sector_exposure.get(sector, 0.0) + requested_value
            elif action == "SELL":
                sector_exposure[sector] = max(0.0, sector_exposure.get(sector, 0.0) - requested_value)

            approved.append(
                TradePrediction(
                    symbol=symbol,
                    action=action,
                    shares=shares,
                    confidence=confidence,
                    reasoning=reasoning,
                    origin=origin,
                )
            )

        return RiskReview(approved=approved, rejected=rejected)

    def _sector_exposure(self, portfolio: PortfolioSnapshot) -> dict[str, float]:
        exposure: dict[str, float] = {}
        for position in portfolio.positions:
            sector = sector_for(position.symbol)
            exposure[sector] = exposure.get(sector, 0.0) + position.market_value
        return exposure

    def _base_rejection_reason(
        self,
        symbol: str,
        action: str,
        shares: int,
        confidence: float,
        prices: dict[str, float],
    ) -> str | None:
        if not symbol:
            return "missing symbol"
        if action not in VALID_ACTIONS:
            return f"invalid action: {action}"
        if action != "HOLD" and shares <= 0:
            return "non-HOLD trade must have positive shares"
        # A HOLD is a no-op (trades nothing), so the minimum-trade-confidence gate
        # doesn't apply — otherwise every low-conviction HOLD is logged as a
        # "rejected trade" that was never a trade. HOLDs are skipped in review().
        if action != "HOLD" and confidence < MIN_TRADE_CONFIDENCE:
            return f"confidence {confidence:.2f} below minimum {MIN_TRADE_CONFIDENCE:.2f}"
        if action != "HOLD" and symbol not in prices:
            return "missing market price"
        return None

    def _parse_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _parse_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
