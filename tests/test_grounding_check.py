"""Runtime grounding check (P2-3): flag ungrounded decisions and block tweeting.

Only a *material* fabrication blocks publication. Minor imprecisions (rounding,
phrasing) are recorded for transparency but must never block — this is the fix for
the 2026-07-06 incident where a tweet was muzzled over "~5%" vs an actual 4.84%.
"""

import os
from datetime import date
from types import SimpleNamespace

import pytest

from src import main
from src.models.portfolio import PortfolioSnapshot
from src.scoring.grounding import GroundingVerdict, check_grounding
from src.storage import decision_store
from src.storage.decision_store import DecisionStore


_DECISION = {"outlook": "BULLISH", "summary": "AAPL looks strong", "trades": []}
_CTX = {"research": {"symbols": []}, "memory": [], "portfolio": {"cash": 1}}


def _check(**kw):
    return check_grounding(_DECISION, research=_CTX["research"], memory=_CTX["memory"],
                           portfolio=_CTX["portfolio"], **kw)


def test_grounded_decision_is_ok():
    result = _check(judge=lambda d, c: GroundingVerdict(grounded=True))
    assert result.status == "ok"
    assert result.grounded is True


def test_material_fabrication_is_flagged():
    verdict = GroundingVerdict(grounded=False, severity="material",
                               issues=["fabricated NVDA price of $999"])
    result = _check(judge=lambda d, c: verdict)
    assert result.status == "flagged"
    assert result.grounded is False
    assert result.severity == "material"
    assert "fabricated" in result.issues[0]


def test_minor_rounding_is_recorded_but_not_blocking():
    # The regression case: an approximation noted as a minor issue must NOT block.
    verdict = GroundingVerdict(
        grounded=True, severity="minor",
        issues=["decision says 'about 5%' where context says 4.84% (rounding)"],
    )
    result = _check(judge=lambda d, c: verdict)
    assert result.status == "ok"  # not "flagged" — the tweet would go out
    assert result.grounded is True
    assert result.issues  # still recorded for transparency


def test_minor_severity_never_blocks_even_if_judge_sets_grounded_false():
    # Defense in depth: blocking is gated on severity == "material" only.
    verdict = GroundingVerdict(grounded=False, severity="minor", issues=["nitpick"])
    result = _check(judge=lambda d, c: verdict)
    assert result.status == "ok"


def test_judge_failure_degrades_to_unavailable_non_blocking():
    def boom(decision, context):
        raise RuntimeError("model down")

    result = _check(judge=boom)
    assert result.status == "unavailable"
    assert result.grounded is True  # never block a run on infra failure


# -- journaling --------------------------------------------------------------


def test_grounding_is_written_to_the_decision_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_store, "DECISIONS_FILE", tmp_path / "decisions.jsonl")
    snapshot = PortfolioSnapshot(date=date.today(), cash=100000, positions=[])
    grounding = {"status": "flagged", "grounded": False, "issues": ["invented earnings beat"]}

    DecisionStore().save(
        portfolio=snapshot,
        raw_decision=_DECISION,
        approved=[],
        rejected=[],
        executed=[],
        grounding=grounding,
        run_id="run_1",
    )

    entry = DecisionStore().load_all()[0]
    assert entry["grounding"] == grounding


# -- tweet blocking ----------------------------------------------------------


def test_flagged_grounding_blocks_tweeting(monkeypatch):
    called = {"published": False}

    def fake_service(text, *, run_id=None):
        called["published"] = True
        return SimpleNamespace(status="posted", to_dict=lambda: {})

    monkeypatch.setattr(main, "publish_tweet_service", fake_service)
    run_status = {}

    result = main.publish_tweet("hype tweet", "run_1", run_status,
                                grounding={"status": "flagged", "grounded": False, "issues": ["x"]})

    assert called["published"] is False  # service never called
    assert result.status == "blocked_grounding"
    assert run_status["tweet_publish"]["posted"] is False
    assert any("grounding" in w for w in run_status["warnings"])


def test_grounded_decision_allows_tweeting(monkeypatch):
    called = {"published": False}

    def fake_service(text, *, run_id=None):
        called["published"] = True
        return SimpleNamespace(status="posted", error=None, to_dict=lambda: {"status": "posted"})

    monkeypatch.setattr(main, "publish_tweet_service", fake_service)
    run_status = {}

    main.publish_tweet("clean tweet", "run_1", run_status,
                       grounding={"status": "ok", "grounded": True, "issues": []})

    assert called["published"] is True


# -- live regression: the real judge must not block on rounding --------------


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a live model for the judge")
def test_live_judge_does_not_block_rounding_approximation():
    """Reproduces the 2026-07-06 incident against the REAL judge: a decision that
    approximates a 4.84% move as '~5%' must not be flagged as material."""
    decision = {
        "outlook": "BULLISH",
        "market_summary": "AAPL has increased approximately 5% over the past five days; "
        "added to the position.",
        "portfolio_assessment": "Cash near 26%.",
        "trades": [{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.7}],
    }
    research = {"symbols": [{"symbol": "AAPL", "price": 312.68, "return_5d": 0.0484, "return_30d": 0.07}]}
    portfolio = {"total_value": 1_022_983, "cash_pct": 0.267}

    result = check_grounding(decision, research=research, memory=[], portfolio=portfolio)

    assert result.severity != "material", f"rounding wrongly flagged material: {result.issues}"
    assert result.status != "flagged"
