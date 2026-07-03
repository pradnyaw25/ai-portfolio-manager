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


class DecisionResponse(BaseModel):
    """Portfolio manager decision. Field set mirrors the prompt contract and
    everything ``main.py`` and the memory/citation layers read downstream."""

    model_config = ConfigDict(extra="allow")

    outlook: str = "NEUTRAL"
    market_summary: str = ""
    portfolio_assessment: str = ""
    cash_thesis: str | None = None
    risk_assessment: str = ""
    trades: list[TradeProposal] = Field(default_factory=list)
    summary: str = ""
    sources_used: list[str] = Field(default_factory=list)


class RebalanceResponse(BaseModel):
    """Rebalance checker deployment decision."""

    model_config = ConfigDict(extra="allow")

    action: Literal["deploy", "hold_cash"] = "hold_cash"
    trades: list[TradeProposal] = Field(default_factory=list)
    cash_thesis: str | None = None
