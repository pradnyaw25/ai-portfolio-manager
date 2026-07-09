"""Scenarios for the ablation harness (roadmap V1-1, `scripts/compare_ablations.py`).

Kept SEPARATE from the gating golden set (``evals.scenarios.SCENARIOS``) on
purpose. The gating set is tuned so a competent model passes every deterministic
scorer in CI; this set is tuned for *ablation signal* — each scenario is one where
retrieved memory or the bull/bear debate should plausibly change the quality of
the decision, so switching a component off actually moves the judge's score
instead of being a no-op. It is not a pass/fail gate.

Reuses the three memory/debate scenarios already in the golden set and adds a few
more so the "no memory" and "no debate" ablations each affect several scenarios
rather than one.
"""

from evals.scenarios import DEBATE, EARNINGS_CONTEXT, STALE_MEMORY, Scenario, _symbols

# --- memory-dependent: the "right" call leans on a fact only in memory ----------

LOSS_LESSON = Scenario(
    name="loss_lesson",
    description="Memory holds a hard-won lesson from a prior losing trade in the "
    "same name; strong 5d momentum tempts a re-entry the lesson warns against.",
    portfolio={"total_value": 1_000_000, "cash": 220_000, "cash_pct": 0.22, "positions": [
        {"symbol": "NVDA", "shares": 400, "avg_cost": 135, "current_price": 148},
    ]},
    research={"symbols": _symbols(
        ("NVDA", 148.0, 0.07, 0.04), ("AMD", 168.0, 0.05, 0.02),
        ("MSFT", 430.0, 0.01, 0.03), ("SPY", 560.0, 0.01, 0.03),
    ), "market_news": [{"title": "Chip stocks rip higher on AI-capex chatter"}]},
    benchmark={"return_pct": 0.03, "current": 560.0},
    memory=[{
        "id": "lesson:nvda-momentum-2026-03-20",
        "type": "lesson",
        "date": "2026-03-20",
        "symbols": ["NVDA"],
        "content": "Added to NVDA on 5d momentum at $152 with no fresh demand "
        "catalyst; gave back -18% over three weeks when the AI-capex narrative "
        "cooled. Lesson: do not chase chip names on short-term momentum alone.",
    }],
    cash_pct=0.22,
)

PRIOR_CONVICTION = Scenario(
    name="prior_conviction",
    description="A prior high-conviction thesis on a defensive holding sits in "
    "memory; the PM can carry the conviction forward or re-derive it blind.",
    portfolio={"total_value": 1_000_000, "cash": 180_000, "cash_pct": 0.18, "positions": [
        {"symbol": "JNJ", "shares": 500, "avg_cost": 240, "current_price": 263},
    ]},
    research={"symbols": _symbols(
        ("JNJ", 263.0, 0.01, 0.04), ("UNH", 505.0, -0.02, 0.01),
        ("PG", 170.0, 0.00, 0.02), ("SPY", 560.0, 0.01, 0.03),
    ), "market_news": [{"title": "Defensives steady as growth wobbles"}]},
    benchmark={"return_pct": 0.03, "current": 560.0},
    memory=[{
        "id": "thesis:jnj-2026-04-10",
        "type": "thesis",
        "date": "2026-04-10",
        "symbols": ["JNJ"],
        "content": "Initiated JNJ as a ballast position: durable dividend, litigation "
        "overhang priced in, defensive earnings quality. Conviction: high; hold "
        "through volatility unless the dividend thesis breaks.",
    }],
    cash_pct=0.18,
)

RISK_FLAG_MEMORY = Scenario(
    name="risk_flag_memory",
    description="Memory carries a standing risk flag on a concentrated holding; "
    "without it the PM sees only a green tape.",
    portfolio={"total_value": 1_000_000, "cash": 90_000, "cash_pct": 0.09, "positions": [
        {"symbol": "TSLA", "shares": 900, "avg_cost": 250, "current_price": 300},
    ]},
    research={"symbols": _symbols(
        ("TSLA", 300.0, 0.06, 0.11), ("AAPL", 205.0, 0.02, 0.05),
        ("MSFT", 430.0, 0.01, 0.03), ("SPY", 560.0, 0.01, 0.04),
    ), "market_news": [{"title": "TSLA rallies on delivery beat"}]},
    benchmark={"return_pct": 0.04, "current": 560.0},
    memory=[{
        "id": "lesson:tsla-concentration-2026-05-05",
        "type": "lesson",
        "date": "2026-05-05",
        "symbols": ["TSLA"],
        "content": "TSLA flagged twice for single-name concentration risk near the "
        "10% cap; forward guidance and regulatory headline risk are elevated. Trim "
        "into strength rather than adding.",
    }],
    cash_pct=0.09,
)

# --- debate-dependent: genuine bull/bear tension the PM must resolve -------------

VALUATION_SPLIT = Scenario(
    name="valuation_split",
    description="Strong recent momentum but stretched valuation and decelerating "
    "long-window returns — a real bull/bear split the debate should surface.",
    portfolio={"total_value": 1_000_000, "cash": 160_000, "cash_pct": 0.16, "positions": [
        {"symbol": "AVGO", "shares": 200, "avg_cost": 1500, "current_price": 1720},
    ]},
    research={"symbols": _symbols(
        ("AVGO", 1720.0, 0.08, -0.02), ("NVDA", 148.0, 0.05, 0.03),
        ("MSFT", 430.0, 0.00, 0.02), ("SPY", 560.0, 0.00, 0.02),
    ), "market_news": [{"title": "Broadcom surges but analysts flag rich multiple"}]},
    benchmark={"return_pct": 0.02, "current": 560.0},
    expects_debate=True,
    cash_pct=0.16,
)

MIXED_MACRO = Scenario(
    name="mixed_macro",
    description="Cross-currents — cooling inflation but softening jobs — with no "
    "clean signal; the bull and bear read the same tape oppositely.",
    portfolio={"total_value": 1_000_000, "cash": 210_000, "cash_pct": 0.21, "positions": [
        {"symbol": "MSFT", "shares": 300, "avg_cost": 400, "current_price": 430},
        {"symbol": "AMZN", "shares": 400, "avg_cost": 190, "current_price": 205},
    ]},
    research={"symbols": _symbols(
        ("MSFT", 430.0, 0.02, 0.04), ("AMZN", 205.0, -0.03, 0.06),
        ("GOOGL", 185.0, 0.01, 0.05), ("SPY", 560.0, -0.01, 0.03),
    ), "market_news": [{"title": "Inflation cools but hiring slows, muddying the outlook"}]},
    benchmark={"return_pct": 0.03, "current": 560.0},
    expects_debate=True,
    cash_pct=0.21,
)


ABLATION_SCENARIOS = [
    # memory-dependent
    STALE_MEMORY,
    EARNINGS_CONTEXT,
    LOSS_LESSON,
    PRIOR_CONVICTION,
    RISK_FLAG_MEMORY,
    # debate-dependent
    DEBATE,
    VALUATION_SPLIT,
    MIXED_MACRO,
]
