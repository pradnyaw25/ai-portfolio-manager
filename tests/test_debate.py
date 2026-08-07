"""Bull/bear/risk debate (P3-1) — analysts, orchestration, and PM synthesis."""

from src.agents import analysts as analysts_mod
from src.agents import portfolio_manager as pm_mod
from src.agents.analysts import BearAnalyst, BullAnalyst, RiskAnalyst
from src.agents.debate import run_debate
from src.llm.schemas import AnalystThesis, DecisionResponse


# -- analysts ----------------------------------------------------------------


def test_analyst_stamps_authoritative_role(monkeypatch):
    # Even if the model mislabels itself, the analyst forces the correct role.
    monkeypatch.setattr(
        analysts_mod, "complete_structured",
        lambda *a, **k: AnalystThesis(role="wrong", thesis="up", conviction=0.8),
    )
    thesis = BullAnalyst().analyze("pf", "research", "bench")
    assert thesis.role == "bull"
    assert thesis.thesis == "up"


def test_each_analyst_uses_its_prompt_version(monkeypatch):
    seen = {}

    def fake(messages, schema, *, tier, prompt_version):
        seen[prompt_version] = tier
        return AnalystThesis(thesis="x")

    monkeypatch.setattr(analysts_mod, "complete_structured", fake)
    for cls in (BullAnalyst, BearAnalyst, RiskAnalyst):
        cls().analyze("pf", "r", "b")

    assert set(seen) == {"bull_analyst/v2", "bear_analyst/v2", "risk_analyst/v2"}
    assert all(tier == "cheap" for tier in seen.values())  # analysts run on the cheap tier


# -- information asymmetry: each analyst sees a different slice ----------------


def test_analysts_get_asymmetric_context():
    pf = {"cash_pct": 0.15, "positions": [{"symbol": "NVDA", "shares": 800, "current_price": 140}]}
    research = {
        "symbols": [{"symbol": "NVDA", "price": 140, "return_5d": 0.06, "return_30d": -0.03}],
        "market_news": [{"title": "Chip demand strong but valuations stretched"}],
        "cash_pct": 0.15,
    }
    bench = {"return_pct": 0.03, "current": 560.0}

    bull = BullAnalyst().build_context(pf, research, bench, None).lower()
    bear = BearAnalyst().build_context(pf, research, bench, None).lower()
    risk = RiskAnalyst().build_context(pf, research, bench, None).lower()

    # bull sees momentum/news, not the exposure breakdown
    assert "momentum & news" in bull and "exposures & concentration" not in bull
    # bear sees downside signals (NVDA's fading 30d), not the exposure breakdown
    assert "downside signals" in bear and "exposures & concentration" not in bear
    assert "nvda" in bear  # the fading-momentum name surfaces for the bear
    # risk sees exposures + sector concentration, not momentum/news
    assert "exposures & concentration" in risk and "sector concentration" in risk
    assert "momentum & news" not in risk


# -- orchestration -----------------------------------------------------------


class _FakeAnalyst:
    def __init__(self, role, conviction=0.6):
        self.role = role
        self.conviction = conviction

    def analyze(self, portfolio, research, benchmark, memory=None):
        return AnalystThesis(role=self.role, thesis=f"{self.role} view", conviction=self.conviction)


class _RebuttingBear(_FakeAnalyst):
    def __init__(self, conviction=0.3):
        super().__init__("bear", conviction)

    def rebut(self, bull_thesis, own_thesis, portfolio, research, benchmark, memory=None):
        return AnalystThesis(role="bear_rebuttal", thesis="still bearish after the bull", conviction=0.35)


class _FakeManager:
    def __init__(self):
        self.received = None

    def decide(self, portfolio, research, benchmark, memory=None, analysts=None):
        self.received = analysts
        return {"outlook": "NEUTRAL", "trades": [], "bear_case_response": "addressed the bear points"}


def test_run_debate_embeds_transcript_and_feeds_pm():
    manager = _FakeManager()
    decision = run_debate(
        "pf", "research", "bench",
        analysts=[_FakeAnalyst("bull"), _FakeAnalyst("bear"), _FakeAnalyst("risk")],
        manager=manager,
    )

    # PM received all three theses...
    assert set(manager.received) == {"bull", "bear", "risk"}
    # ...and the transcript is embedded in the returned decision.
    assert set(decision["debate"]) == {"bull", "bear", "risk"}
    assert decision["debate"]["bear"]["thesis"] == "bear view"
    assert decision["bear_case_response"] == "addressed the bear points"


def test_run_debate_adds_rebuttal_and_conviction_spread():
    manager = _FakeManager()
    decision = run_debate(
        "pf", "research", "bench",
        analysts=[_FakeAnalyst("bull", 0.9), _RebuttingBear(0.3), _FakeAnalyst("risk", 0.5)],
        manager=manager,
    )

    # the bear rebutted the bull — a real second turn, not a parallel monologue
    assert decision["debate"]["bear_rebuttal"]["thesis"] == "still bearish after the bull"
    # PM saw the rebuttal in the transcript too
    assert "bear_rebuttal" in manager.received
    # spread = max(0.9, 0.3, 0.5) - min = 0.6, rebuttal excluded
    assert decision["conviction_spread"] == 0.6


def test_conviction_spread_excludes_rebuttal_and_needs_two():
    from src.agents.debate import conviction_spread

    assert conviction_spread(
        {"bull": {"conviction": 0.9}, "bear": {"conviction": 0.3}, "risk": {"conviction": 0.5}}
    ) == 0.6
    # rebuttal is not counted toward the spread
    assert conviction_spread(
        {"bull": {"conviction": 0.5}, "bear": {"conviction": 0.5}, "risk": {"conviction": 0.5},
         "bear_rebuttal": {"conviction": 0.1}}
    ) == 0.0
    # fewer than two convictions → 0
    assert conviction_spread({"bull": {"conviction": 0.7}}) == 0.0


# -- PM synthesis requires the bear-case response ----------------------------


def test_pm_requests_bear_case_response_when_given_analysts(monkeypatch):
    captured = {}

    def fake(messages, schema, *, tier, prompt_version):
        captured["prompt"] = messages[0]["content"]
        captured["tier"] = tier
        return DecisionResponse(outlook="BULLISH", bear_case_response="rebutted")

    monkeypatch.setattr(pm_mod, "complete_structured", fake)
    analysts = {"bull": {"thesis": "up"}, "bear": {"thesis": "down"}, "risk": {"thesis": "concentrated"}}

    result = pm_mod.PortfolioManagerAgent().decide("pf", "r", "b", analysts=analysts)

    assert "bear_case_response" in captured["prompt"]
    assert "committee debate" in captured["prompt"]
    assert captured["tier"] == "strong"  # PM synthesis uses the strong tier
    assert result["bear_case_response"] == "rebutted"


def test_pm_omits_bear_case_prompt_without_analysts(monkeypatch):
    captured = {}

    def fake(messages, schema, **k):
        captured["prompt"] = messages[0]["content"]
        return DecisionResponse()

    monkeypatch.setattr(pm_mod, "complete_structured", fake)
    pm_mod.PortfolioManagerAgent().decide("pf", "r", "b")
    assert "committee debate" not in captured["prompt"]


# --- fund-memory routing ----------------------------------------------------


def _memory_groups():
    """The shape the pipeline actually passes: run.memory_groups, a dict of buckets.

    See src/models/run_state.py (memory_groups: dict[str, list[dict]]) and
    format_grouped_memory_for_prompt in src/memory/retriever.py.
    """
    return {
        "symbol_theses": [{"id": "m1", "type": "thesis", "content": "AAPL momentum intact"}],
        "risk_lessons": [{"id": "m2", "type": "risk_lesson", "content": "trim into weakness"}],
        "recent_trades": [{"id": "m3", "type": "trade", "content": "BUY AAPL"}],
        "macro": [{"id": "m4", "type": "macro_regime", "content": "rates steady"}],
    }


def _ctx(analyst, memory):
    pf = {"cash_pct": 0.15, "positions": [{"symbol": "AAPL", "shares": 10, "current_price": 300}]}
    research = {"symbols": [{"symbol": "AAPL", "price": 300, "return_5d": 0.01, "return_30d": 0.02}]}
    return analyst.build_context(pf, research, {"return_pct": 0.03}, memory)


def test_analysts_receive_the_grouped_memory_the_pipeline_passes():
    """Regression: the debate ran with no memory at all for months.

    daily_graph passes run.memory_groups (a dict). _memory_block iterated it directly,
    so it walked the dict's KEYS — bare strings — every isinstance(m, dict) was False,
    and both analysts got an empty memory block. The routing below was dead code in
    production; the tests only ever passed memory=None and never caught it.
    """
    bull = _ctx(BullAnalyst(), _memory_groups())
    bear = _ctx(BearAnalyst(), _memory_groups())

    assert "AAPL momentum intact" in bull
    assert "trim into weakness" in bear


def test_memory_routing_keeps_the_two_lenses_separate():
    """Information asymmetry is the point — if both sides see everything, the debate
    collapses into two parallel monologues that agree."""
    bull = _ctx(BullAnalyst(), _memory_groups())
    bear = _ctx(BearAnalyst(), _memory_groups())

    # Assert both actually received memory first — otherwise "separate" is satisfied
    # trivially by the very bug this file exists to catch.
    assert "fund memory" in bull and "fund memory" in bear

    assert "trim into weakness" not in bull  # cautionary memory is the bear's
    assert "AAPL momentum intact" not in bear  # constructive memory is the bull's


def test_a_flat_memory_list_still_works():
    """Older callers and tests pass a flat list; both shapes must be accepted."""
    flat = [m for group in _memory_groups().values() for m in group]

    assert "AAPL momentum intact" in _ctx(BullAnalyst(), flat)


def test_absent_or_malformed_memory_is_harmless():
    for memory in (None, {}, [], "a string", {"symbol_theses": None}):
        assert "fund memory" not in _ctx(BullAnalyst(), memory)
