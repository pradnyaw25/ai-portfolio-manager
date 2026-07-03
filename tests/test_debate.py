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

    assert set(seen) == {"bull_analyst/v1", "bear_analyst/v1", "risk_analyst/v1"}
    assert all(tier == "cheap" for tier in seen.values())  # analysts run on the cheap tier


# -- orchestration -----------------------------------------------------------


class _FakeAnalyst:
    def __init__(self, role):
        self.role = role

    def analyze(self, portfolio, research, benchmark, memory=None):
        return AnalystThesis(role=self.role, thesis=f"{self.role} view", conviction=0.6)


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
