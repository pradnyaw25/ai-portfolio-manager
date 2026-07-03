"""Pydantic response schemas for LLM structured outputs.

These validate the shape of model responses at the gateway boundary. They are
deliberately lenient about trade fields — the deterministic ``RiskManagerAgent``
re-coerces and re-validates every trade downstream — so validation catches
structural breakage (missing keys, wrong container types) without rejecting
valid-but-sloppy model output and turning it into a failed run.

Named ``*Response`` to avoid colliding with the ``PortfolioDecision`` dataclass
in :mod:`src.models`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TradeProposal(BaseModel):
    """A single proposed trade from an LLM agent.

    Lenient by design: the risk manager coerces types and enforces limits, so
    here we only require a symbol and action and let the rest default.
    """

    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=False)

    symbol: str
    action: str
    shares: float = 0
    confidence: float = 0.0
    reason: str = ""
    risks: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)


class AnalystThesis(BaseModel):
    """A single analyst's structured argument (bull / bear / risk)."""

    model_config = ConfigDict(extra="allow")

    role: str = ""
    thesis: str = ""
    key_points: list[str] = Field(default_factory=list)
    focus_symbols: list[str] = Field(default_factory=list)
    conviction: float = 0.5


class DecisionResponse(BaseModel):
    """Portfolio manager decision. Field set mirrors the prompt contract and
    everything ``main.py`` and the memory/citation layers read downstream."""

    model_config = ConfigDict(extra="allow")

    outlook: str = "NEUTRAL"
    market_summary: str = ""
    portfolio_assessment: str = ""
    cash_thesis: str | None = None
    risk_assessment: str = ""
    bear_case_response: str = ""
    trades: list[TradeProposal] = Field(default_factory=list)
    summary: str = ""
    sources_used: list[str] = Field(default_factory=list)


class RebalanceResponse(BaseModel):
    """Rebalance checker deployment decision."""

    model_config = ConfigDict(extra="allow")

    action: Literal["deploy", "hold_cash"] = "hold_cash"
    trades: list[TradeProposal] = Field(default_factory=list)
    cash_thesis: str | None = None


class ReflectionLesson(BaseModel):
    """A single lesson synthesized from resolved predictions and trades.

    ``cited_ids`` are the prediction/trade ids the lesson is grounded in — its
    provenance, recorded on the resulting memory.
    """

    model_config = ConfigDict(extra="allow")

    lesson_type: Literal["risk_lesson", "mistake"] = "risk_lesson"
    content: str = ""
    symbols: list[str] = Field(default_factory=list)
    cited_ids: list[str] = Field(default_factory=list)


class ReflectionResponse(BaseModel):
    """The reflection agent's weekly set of lessons."""

    model_config = ConfigDict(extra="allow")

    lessons: list[ReflectionLesson] = Field(default_factory=list)
