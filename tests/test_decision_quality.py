import pytest
from pydantic import ValidationError

from src.scoring.decision_quality import DecisionQuality, score_decision_quality


def test_overall_is_mean_of_three_dimensions():
    q = DecisionQuality(reasoning=4, specificity=5, risk_awareness=3)
    assert q.overall == round((4 + 5 + 3) / 3, 3)


def test_score_uses_injected_judge_without_api():
    captured = {}

    def fake_judge(decision, context):
        captured["decision"] = decision
        captured["context"] = context
        return DecisionQuality(reasoning=5, specificity=4, risk_awareness=4, notes="solid")

    q = score_decision_quality({"summary": "s"}, {"portfolio": {"cash": 1}}, judge=fake_judge)

    assert q.reasoning == 5 and q.specificity == 4 and q.risk_awareness == 4
    assert q.overall == round((5 + 4 + 4) / 3, 3)
    assert captured["decision"] == {"summary": "s"}
    assert captured["context"] == {"portfolio": {"cash": 1}}


@pytest.mark.parametrize("bad", [0, 6, -1])
def test_scores_must_be_within_one_to_five(bad):
    with pytest.raises(ValidationError):
        DecisionQuality(reasoning=bad, specificity=3, risk_awareness=3)
