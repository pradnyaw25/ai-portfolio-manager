"""Bull/bear/risk debate → portfolio manager synthesis.

Runs the three analysts (cheap tier), then the portfolio manager (strong tier)
synthesizes their theses into the final decision while explicitly responding to
the bear case. The debate transcript is embedded in the returned decision under
``debate`` so it flows into the decision journal and dashboard.
"""

from src.agents.analysts import DEFAULT_ANALYSTS
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run_debate(portfolio, research, benchmark, memory=None, *, analysts=None, manager=None) -> dict:
    analysts = analysts if analysts is not None else [cls() for cls in DEFAULT_ANALYSTS]
    manager = manager or PortfolioManagerAgent()

    transcript = {}
    for analyst in analysts:
        thesis = analyst.analyze(portfolio, research, benchmark, memory)
        transcript[analyst.role] = thesis.model_dump()
        logger.info("Analyst %s conviction=%.2f", analyst.role, transcript[analyst.role].get("conviction", 0.0))

    decision = manager.decide(portfolio, research, benchmark, memory=memory, analysts=transcript)
    decision["debate"] = transcript
    return decision
