"""Analyst agents for the bull/bear/risk debate.

Each analyst produces a structured thesis from the same context, on the cheap
model tier. The portfolio manager (strong tier) then synthesizes them into the
final decision and must explicitly respond to the bear case.
"""

import json

from src.llm import complete_structured
from src.llm.schemas import AnalystThesis


def _context_block(portfolio, research, benchmark, memory) -> str:
    block = (
        f"Portfolio snapshot:\n{portfolio}\n\n"
        f"Market context:\n{research}\n\n"
        f"Benchmark:\n{benchmark}\n"
    )
    if memory:
        block += f"\nFund memory:\n{json.dumps(memory, default=str)[:4000]}\n"
    return block


class _Analyst:
    role = ""
    prompt_version = ""
    instruction = ""

    def analyze(self, portfolio, research, benchmark, memory=None) -> AnalystThesis:
        prompt = (
            f"{self.instruction}\n\n"
            f"{_context_block(portfolio, research, benchmark, memory)}\n"
            "Ground your argument only in symbols and facts present in the context; "
            "do not invent prices or events.\n\n"
            'Return JSON: {"thesis": "...", "key_points": ["..."], '
            '"focus_symbols": ["AAPL"], "conviction": 0.0-1.0}'
        )
        thesis = complete_structured(
            [{"role": "user", "content": prompt}],
            AnalystThesis,
            tier="cheap",
            prompt_version=self.prompt_version,
        )
        thesis.role = self.role  # authoritative — don't trust the model to label itself
        return thesis


class BullAnalyst(_Analyst):
    role = "bull"
    prompt_version = "bull_analyst/v1"
    instruction = (
        "You are the BULL analyst on an investment committee. Make the strongest "
        "evidence-based case FOR buying or holding, citing momentum, relative "
        "strength, and catalysts visible in the context. Be persuasive but honest."
    )


class BearAnalyst(_Analyst):
    role = "bear"
    prompt_version = "bear_analyst/v1"
    instruction = (
        "You are the BEAR analyst on an investment committee. Make the strongest "
        "evidence-based case AGAINST the current holdings and candidates: downside "
        "risks, deteriorating momentum, valuation, and macro headwinds visible in "
        "the context. Your job is to find what could go wrong."
    )


class RiskAnalyst(_Analyst):
    role = "risk"
    prompt_version = "risk_analyst/v1"
    instruction = (
        "You are the RISK analyst on an investment committee. Assess portfolio risk: "
        "position concentration, sector tilt, drawdown, volatility, and cash level. "
        "Flag the biggest risks to capital, independent of directional view."
    )


DEFAULT_ANALYSTS = (BullAnalyst, BearAnalyst, RiskAnalyst)
