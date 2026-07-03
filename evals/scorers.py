"""Deterministic scorers for decision evals.

Each returns a ScoreResult. These are the hard gate — robust to LLM wording
variation because they check structure and rule compliance, not prose.
"""

from dataclasses import dataclass

from src.memory.citations import review_memory_citations


@dataclass
class ScoreResult:
    name: str
    passed: bool
    detail: str = ""


def score_schema_validity(decision, scenario) -> ScoreResult:
    """The decision must be a dict with the required keys and well-formed trades."""
    if not isinstance(decision, dict):
        return ScoreResult("schema_validity", False, "decision is not a dict")

    issues = []
    for key in ("outlook", "summary", "trades"):
        if key not in decision:
            issues.append(f"missing '{key}'")

    trades = decision.get("trades")
    if not isinstance(trades, list):
        issues.append("'trades' is not a list")
    else:
        for i, trade in enumerate(trades):
            if not isinstance(trade, dict):
                issues.append(f"trade[{i}] is not an object")
                continue
            for key in ("symbol", "action", "confidence"):
                if key not in trade:
                    issues.append(f"trade[{i}] missing '{key}'")

    return ScoreResult("schema_validity", not issues, "; ".join(issues))


def score_risk_compliance(decision, scenario) -> ScoreResult:
    """Trades stay in the tradable universe with valid actions/confidence; high
    cash is either deployed or justified with a thesis."""
    issues = []
    allowed = {s.upper() for s in scenario.tradable_symbols()}
    trades = decision.get("trades") or []
    has_buy = False

    for trade in trades:
        if not isinstance(trade, dict):
            continue
        symbol = str(trade.get("symbol", "")).upper()
        action = str(trade.get("action", "")).upper()

        if action not in {"BUY", "SELL", "HOLD"}:
            issues.append(f"{symbol or 'UNKNOWN'}: invalid action '{action}'")
        if action == "BUY":
            has_buy = True
        if action in {"BUY", "SELL"} and symbol not in allowed:
            issues.append(f"{symbol}: not in tradable universe {sorted(allowed)}")

        try:
            confidence = float(trade.get("confidence"))
            if not 0.0 <= confidence <= 1.0:
                issues.append(f"{symbol}: confidence {confidence} out of [0,1]")
        except (TypeError, ValueError):
            issues.append(f"{symbol}: non-numeric confidence")

    if scenario.expects_cash_thesis:
        thesis = (decision.get("cash_thesis") or "").strip()
        if not has_buy and not thesis:
            issues.append("cash above target but no deploying BUY and no cash_thesis")

    return ScoreResult("risk_compliance", not issues, "; ".join(issues))


def score_citation_validity(decision, scenario) -> ScoreResult:
    """Any cited memory IDs must exist in the scenario's provided memory."""
    review = review_memory_citations(raw_decision=decision, memory_used=scenario.memory)
    return ScoreResult("citation_validity", not review.warnings, "; ".join(review.warnings))


DETERMINISTIC_SCORERS = [
    score_schema_validity,
    score_risk_compliance,
    score_citation_validity,
]
