"""Runtime grounding check (P2-3): flag ungrounded decisions and block tweeting."""

from datetime import date
from types import SimpleNamespace

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


def test_ungrounded_decision_is_flagged():
    verdict = GroundingVerdict(grounded=False, issues=["fabricated NVDA price of $999"])
    result = _check(judge=lambda d, c: verdict)
    assert result.status == "flagged"
    assert result.grounded is False
    assert "fabricated" in result.issues[0]


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
