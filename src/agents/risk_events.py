"""Deterministic risk-engine exits: stop-loss and take-profit.

Independent of the LLM: scans marked-to-market positions and emits system SELL
proposals for any position that has fallen past the stop-loss threshold or risen
past the take-profit threshold (as a fraction of cost basis). These are routed
through the normal ``RiskManagerAgent`` and execution pipeline like any trade, and
journaled as first-class risk events tagged ``origin="system"``.
"""

from src.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT
from src.models.portfolio import PortfolioSnapshot


def _sell_event(position, *, kind: str, reason: str) -> dict:
    return {
        "symbol": position.symbol,
        "action": "SELL",
        "shares": int(position.shares),
        "confidence": 1.0,  # deterministic — always clears the confidence gate
        "reason": reason,
        "origin": "system",
        "risk_event": kind,
        "return_pct": round(position.return_pct, 4),
    }


def generate_risk_events(
    portfolio: PortfolioSnapshot,
    *,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
) -> list[dict]:
    """Return system SELL proposals (full exits) for threshold-breaching positions.

    Stop-loss takes precedence conceptually, but a position can only breach one
    side at a time. Positions with no cost basis or non-positive shares are skipped.
    """
    events: list[dict] = []
    for position in portfolio.positions:
        if position.shares <= 0 or position.cost_basis == 0:
            continue

        return_pct = position.return_pct
        if return_pct <= -abs(stop_loss_pct):
            events.append(
                _sell_event(
                    position,
                    kind="stop_loss",
                    reason=f"stop-loss: {position.symbol} down "
                    f"{return_pct:.0%} from cost basis",
                )
            )
        elif return_pct >= take_profit_pct:
            events.append(
                _sell_event(
                    position,
                    kind="take_profit",
                    reason=f"take-profit: {position.symbol} up "
                    f"{return_pct:.0%} from cost basis",
                )
            )
    return events
