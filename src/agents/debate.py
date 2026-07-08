"""Bull/bear/risk debate → portfolio manager synthesis.

Runs the three analysts (cheap tier) on **asymmetric** context slices, gives the
bear a **rebuttal turn** against the bull, records a **conviction-spread** metric
(how much the analysts actually disagree), then the portfolio manager (strong
tier) synthesizes it into the final decision while responding to the bear case.

The transcript, rebuttal, and conviction_spread are embedded in the returned
decision so they flow into the decision journal and dashboard.
"""

from src.agents.analysts import DEFAULT_ANALYSTS
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.utils.logger import get_logger

logger = get_logger(__name__)


def conviction_spread(transcript: dict) -> float:
    """Max−min conviction across the primary analysts (bull/bear/risk). A wider
    spread means the analysts genuinely disagreed; clustering means they didn't.
    The rebuttal is excluded so the metric stays comparable across runs."""
    convs = [
        transcript[role].get("conviction")
        for role in ("bull", "bear", "risk")
        if role in transcript and transcript[role].get("conviction") is not None
    ]
    return round(max(convs) - min(convs), 3) if len(convs) >= 2 else 0.0


def run_debate(portfolio, research, benchmark, memory=None, *, analysts=None, manager=None) -> dict:
    analysts = analysts if analysts is not None else [cls() for cls in DEFAULT_ANALYSTS]
    manager = manager or PortfolioManagerAgent()

    transcript = {}
    for analyst in analysts:
        thesis = analyst.analyze(portfolio, research, benchmark, memory)
        transcript[analyst.role] = thesis.model_dump()
        logger.info("Analyst %s conviction=%.2f", analyst.role, transcript[analyst.role].get("conviction", 0.0))

    # Rebuttal turn: the bear responds to the bull's actual case. Only when both a
    # bull thesis and a rebuttal-capable bear are present (fakes in tests skip it).
    bear = next((a for a in analysts if getattr(a, "role", "") == "bear"), None)
    if "bull" in transcript and bear is not None and hasattr(bear, "rebut"):
        rebuttal = bear.rebut(transcript["bull"], transcript["bear"], portfolio, research, benchmark, memory)
        transcript["bear_rebuttal"] = rebuttal.model_dump()
        logger.info("Bear rebuttal conviction=%.2f", transcript["bear_rebuttal"].get("conviction", 0.0))

    spread = conviction_spread(transcript)
    logger.info("Debate conviction spread=%.2f", spread)

    decision = manager.decide(portfolio, research, benchmark, memory=memory, analysts=transcript)
    decision["debate"] = transcript
    decision["conviction_spread"] = spread
    return decision
