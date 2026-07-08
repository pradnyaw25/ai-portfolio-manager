"""Analyst agents for the bull/bear/risk debate.

Each analyst argues from a **different slice** of the shared context (information
asymmetry) so their conclusions can genuinely diverge, not cluster:

* bull  ← price momentum + news, and constructive fund memory
* bear  ← downside signals (holdings in the red, fading momentum) + cautionary
          memory (risk lessons, past mistakes, earnings events)
* risk  ← computed exposures (position + sector concentration, cash)

The bear also gets a **rebuttal turn** against the bull (real interaction, not
three parallel monologues). All analysts run on the cheap tier; the portfolio
manager (strong tier) synthesizes the theses + rebuttal into the final decision.

The slice builders are defensive: they accept dicts, snapshot objects, or the
plain strings used in unit tests, and fall back to stringifying the raw context.
"""

import json

from src.config import sector_for
from src.llm import complete_structured
from src.llm.schemas import AnalystThesis

# Fund-memory routing: each side sees the memory that fits its lens.
_BULL_MEMORY_TYPES = {"thesis", "report_summary", "macro_regime"}
_BEAR_MEMORY_TYPES = {"risk_lesson", "mistake", "earnings_event"}


def _as_dict(obj) -> dict:
    return obj if isinstance(obj, dict) else {}


def _shell(portfolio, benchmark, lens_block: str) -> str:
    return (
        f"Portfolio snapshot:\n{portfolio}\n\n"
        f"Benchmark:\n{benchmark}\n\n"
        f"{lens_block}"
    )


def _memory_block(memory, types: set[str], label: str) -> str:
    if not memory:
        return ""
    picked = [m for m in memory if isinstance(m, dict) and m.get("type") in types]
    if not picked:
        return ""
    return f"\n{label} fund memory:\n{json.dumps(picked, default=str)[:2500]}\n"


def _positions(portfolio, research) -> list[dict]:
    """Normalize holdings to [{symbol, market_value}] from whatever shape is given."""
    holdings = _as_dict(research).get("holdings")
    if holdings:
        return [h for h in holdings if isinstance(h, dict)]

    raw = None
    if isinstance(portfolio, dict):
        raw = portfolio.get("positions")
    elif hasattr(portfolio, "positions"):
        raw = portfolio.positions
    out = []
    for p in raw or []:
        if isinstance(p, dict):
            mv = p.get("market_value")
            if mv is None and p.get("shares") is not None and p.get("current_price") is not None:
                mv = p["shares"] * p["current_price"]
            out.append({"symbol": p.get("symbol"), "market_value": mv or 0})
        else:  # Position object
            out.append({"symbol": getattr(p, "symbol", None), "market_value": getattr(p, "market_value", 0) or 0})
    return out


def _momentum_lens(research) -> str:
    r = _as_dict(research)
    parts = ["YOUR EVIDENCE — momentum & news:"]
    syms = [s for s in (r.get("symbols") or []) if isinstance(s, dict)]
    if syms:
        parts.append(
            "Price momentum:\n"
            + "\n".join(f"  {s.get('symbol')}: 5d {s.get('return_5d')}, 30d {s.get('return_30d')}" for s in syms)
        )
    if r.get("holdings_news"):
        parts.append("Holdings news:\n" + json.dumps(r["holdings_news"], default=str)[:2000])
    if r.get("market_news"):
        parts.append("Market news:\n" + json.dumps(r["market_news"], default=str)[:1500])
    if len(parts) == 1:
        parts.append(str(research))  # fallback for non-dict research (tests)
    return "\n\n".join(parts)


def _downside_lens(portfolio, research) -> str:
    r = _as_dict(research)
    parts = ["YOUR EVIDENCE — downside signals:"]
    red = [h for h in _positions(portfolio, research) if (h.get("return_pct") or 0) < 0]
    holdings = [h for h in (r.get("holdings") or []) if isinstance(h, dict) and (h.get("return_pct") or 0) < 0]
    red = red or holdings
    if red:
        parts.append("Holdings in the red:\n" + "\n".join(f"  {h.get('symbol')}: {h.get('return_pct')}" for h in red))
    fading = [s for s in (r.get("symbols") or []) if isinstance(s, dict) and (s.get("return_30d") or 0) < 0]
    if fading:
        parts.append(
            "Fading 30d momentum:\n" + "\n".join(f"  {s.get('symbol')}: 30d {s.get('return_30d')}" for s in fading)
        )
    if len(parts) == 1:
        parts.append(str(research))
    return "\n\n".join(parts)


def _exposure_lens(portfolio, research) -> str:
    r = _as_dict(research)
    parts = ["YOUR EVIDENCE — exposures & concentration:"]
    holdings = _positions(portfolio, research)
    total = sum((h.get("market_value") or 0) for h in holdings)
    if total > 0:
        weights = sorted(
            ((h.get("symbol"), (h.get("market_value") or 0) / total) for h in holdings), key=lambda x: -x[1]
        )
        parts.append(
            "Position weights (% of invested):\n" + "\n".join(f"  {sym}: {w * 100:.1f}%" for sym, w in weights)
        )
        sectors: dict[str, float] = {}
        for h in holdings:
            sectors[sector_for(h.get("symbol"))] = sectors.get(sector_for(h.get("symbol")), 0.0) + (
                (h.get("market_value") or 0) / total
            )
        parts.append(
            "Sector concentration:\n"
            + "\n".join(f"  {s}: {w * 100:.1f}%" for s, w in sorted(sectors.items(), key=lambda x: -x[1]))
        )
    cash_pct = r.get("cash_pct")
    if cash_pct is None and isinstance(portfolio, dict):
        cash_pct = portfolio.get("cash_pct")
    if cash_pct is None:
        cash_pct = getattr(portfolio, "cash_pct", None)
    if cash_pct is not None:
        parts.append(f"Cash: {cash_pct * 100:.1f}% of portfolio")
    if len(parts) == 1:
        parts.append(str(portfolio))
    return "\n\n".join(parts)


class _Analyst:
    role = ""
    prompt_version = ""
    instruction = ""

    def build_context(self, portfolio, research, benchmark, memory) -> str:
        # Default: full context. Subclasses narrow this to their own slice.
        block = f"Market context:\n{research}\n"
        if memory:
            block += f"\nFund memory:\n{json.dumps(memory, default=str)[:3000]}\n"
        return _shell(portfolio, benchmark, block)

    def analyze(self, portfolio, research, benchmark, memory=None) -> AnalystThesis:
        prompt = (
            f"{self.instruction}\n\n"
            "You are shown only the evidence for your lens — argue from THIS evidence.\n\n"
            f"{self.build_context(portfolio, research, benchmark, memory)}\n"
            "Ground your argument only in facts present above; do not invent prices or "
            "events. Your conviction (0-1) should reflect how strong YOUR evidence is.\n\n"
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
    prompt_version = "bull_analyst/v2"
    instruction = (
        "You are the BULL analyst on an investment committee. Make the strongest "
        "evidence-based case FOR buying or holding, citing momentum, relative "
        "strength, and catalysts. Be persuasive but honest."
    )

    def build_context(self, portfolio, research, benchmark, memory) -> str:
        lens = _momentum_lens(research) + _memory_block(memory, _BULL_MEMORY_TYPES, "Constructive")
        return _shell(portfolio, benchmark, lens)


class BearAnalyst(_Analyst):
    role = "bear"
    prompt_version = "bear_analyst/v2"
    instruction = (
        "You are the BEAR analyst on an investment committee. Make the strongest "
        "evidence-based case AGAINST the current holdings and candidates: downside "
        "risks, deteriorating momentum, and headwinds. Your job is to find what "
        "could go wrong."
    )

    def build_context(self, portfolio, research, benchmark, memory) -> str:
        lens = _downside_lens(portfolio, research) + _memory_block(memory, _BEAR_MEMORY_TYPES, "Cautionary")
        return _shell(portfolio, benchmark, lens)

    def rebut(self, bull_thesis, own_thesis, portfolio, research, benchmark, memory=None) -> AnalystThesis:
        """Second bear turn: respond to the bull's specific claims (the interaction
        that makes this a debate, not parallel monologues)."""
        prompt = (
            "You are the BEAR analyst. The BULL just argued:\n"
            f"{json.dumps(bull_thesis, default=str)[:2000]}\n\n"
            "Your original bear thesis was:\n"
            f"{json.dumps(own_thesis, default=str)[:2000]}\n\n"
            f"{self.build_context(portfolio, research, benchmark, memory)}\n"
            "Rebut the bull's specific claims point by point using your evidence. "
            "Concede any point that is genuinely strong. Set conviction to your view "
            "AFTER hearing the bull — raise it if the bull is weak, lower it if the "
            "bull is convincing.\n\n"
            'Return JSON: {"thesis": "...", "key_points": ["..."], '
            '"focus_symbols": ["..."], "conviction": 0.0-1.0}'
        )
        rebuttal = complete_structured(
            [{"role": "user", "content": prompt}],
            AnalystThesis,
            tier="cheap",
            prompt_version="bear_rebuttal/v1",
        )
        rebuttal.role = "bear_rebuttal"
        return rebuttal


class RiskAnalyst(_Analyst):
    role = "risk"
    prompt_version = "risk_analyst/v2"
    instruction = (
        "You are the RISK analyst on an investment committee. Assess portfolio risk "
        "from the exposures shown: position concentration, sector tilt, and cash "
        "level. Flag the biggest risks to capital, independent of directional view."
    )

    def build_context(self, portfolio, research, benchmark, memory) -> str:
        return _shell(portfolio, benchmark, _exposure_lens(portfolio, research))


DEFAULT_ANALYSTS = (BullAnalyst, BearAnalyst, RiskAnalyst)
