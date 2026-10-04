from src.scoring.calibration import (
    compute_calibration_by_model,
    constant_call_baseline,
)
from src.scoring.calibration import compute_calibration, empty_calibration, was_correct


def _resolved(confidence, outperformed):
    return {
        "status": "scored",
        "confidence": confidence,
        "result": {"outperformed": outperformed},
    }


def test_empty_history_returns_empty_calibration():
    assert compute_calibration([]) == empty_calibration()
    # Open (unresolved) predictions are ignored.
    assert compute_calibration([{"status": "open", "confidence": 0.9, "result": None}])["sample_size"] == 0


def test_brier_score_perfect_predictions_is_zero():
    preds = [_resolved(1.0, True), _resolved(0.0, False)]
    result = compute_calibration(preds)
    assert result["brier_score"] == 0.0
    assert result["sample_size"] == 2
    assert result["win_rate"] == 0.5


def test_brier_score_confidently_wrong_is_one():
    # Confidence 1.0 but the outcome was a loss → (1-0)^2 = 1.
    result = compute_calibration([_resolved(1.0, False)])
    assert result["brier_score"] == 1.0


def test_brier_score_matches_manual_calculation():
    # (0.8-1)^2 = 0.04, (0.6-0)^2 = 0.36 → mean 0.20
    result = compute_calibration([_resolved(0.8, True), _resolved(0.6, False)])
    assert result["brier_score"] == 0.2


def test_buckets_group_by_confidence_and_report_win_rate():
    preds = [
        _resolved(0.72, True),
        _resolved(0.78, False),  # bucket 0.7–0.8: 2 preds, 1 win → actual 0.5
        _resolved(0.93, True),   # bucket 0.9–1.0: 1 pred, 1 win → actual 1.0
    ]
    result = compute_calibration(preds)
    buckets = {(b["lower"], b["upper"]): b for b in result["buckets"]}

    assert buckets[(0.7, 0.8)]["count"] == 2
    assert buckets[(0.7, 0.8)]["actual"] == 0.5
    assert buckets[(0.7, 0.8)]["predicted"] == 0.75
    assert buckets[(0.9, 1.0)]["actual"] == 1.0
    assert buckets[(0.9, 1.0)]["count"] == 1


def test_confidence_of_one_lands_in_last_bucket():
    result = compute_calibration([_resolved(1.0, True)])
    assert result["buckets"][0]["lower"] == 0.9
    assert result["buckets"][0]["upper"] == 1.0


# --- Correct call vs. "beat SPY" -------------------------------------------------
# The fund predicts in BOTH directions. Reading `outperformed` as correctness
# inverted the outcome for every underperform call (75 of the first 109
# predictions), which understated published accuracy and flipped the Brier score.


def _directional(confidence, *, outperformed, correct):
    return {
        "status": "scored",
        "confidence": confidence,
        "result": {"outperformed": outperformed, "correct": correct},
    }


def test_correct_underperform_call_is_a_win_even_though_it_lagged_spy():
    # "X will underperform SPY" at 0.9 confidence; X duly lagged. The call was
    # RIGHT, so the outcome is 1 and Brier is (0.9 - 1)^2 = 0.01 — not (0.9 - 0)^2.
    result = compute_calibration([_directional(0.9, outperformed=False, correct=True)])

    assert result["win_rate"] == 1.0
    assert result["brier_score"] == 0.01
    assert result["buckets"][0]["actual"] == 1.0


def test_wrong_underperform_call_is_a_loss_even_though_it_beat_spy():
    result = compute_calibration([_directional(0.9, outperformed=True, correct=False)])

    assert result["win_rate"] == 0.0
    assert result["brier_score"] == 0.81


def test_legacy_rows_without_correct_fall_back_to_outperformed():
    # Pre-`correct` rows were all outperform bets, so the two fields agree.
    assert was_correct({"result": {"outperformed": True}}) is True
    assert was_correct({"result": {"outperformed": False}}) is False


def test_was_correct_prefers_correct_over_outperformed():
    assert was_correct({"result": {"outperformed": False, "correct": True}}) is True
    assert was_correct({"result": {"outperformed": True, "correct": False}}) is False


def test_was_correct_is_none_when_unresolved():
    assert was_correct({"result": None}) is None
    assert was_correct({}) is None


# --- the base rate and the model swap ----------------------------------------


def _call(direction, outperformed, *, model=None, date="2026-07-15", confidence=0.6):
    correct = (direction == "OUTPERFORM") == outperformed
    return {
        "status": "scored",
        "model": model,
        "date": date,
        "confidence": confidence,
        "result": {"outperformed": outperformed, "correct": correct},
    }


def test_constant_call_baseline_is_the_majority_outcome():
    """July 2026: 59% of names lagged SPY, so "always UNDERPERFORM" scores 59%
    without reading anything. The fund's 56% that month was *below* that."""
    rows = [_call("UNDERPERFORM", False)] * 59 + [_call("OUTPERFORM", True)] * 41

    baseline = constant_call_baseline(rows)

    assert baseline == {
        "sample_size": 100,
        "outperform_rate": 0.41,
        "best_call": "UNDERPERFORM",
        "hit_rate": 0.59,
    }


def test_constant_call_baseline_flips_with_the_regime():
    rows = [_call("OUTPERFORM", True)] * 7 + [_call("OUTPERFORM", False)] * 3

    assert constant_call_baseline(rows)["best_call"] == "OUTPERFORM"
    assert constant_call_baseline(rows)["hit_rate"] == 0.7


def test_constant_call_baseline_ignores_direction_and_unscored_rows():
    """The baseline is about what happened, not what was called."""
    rows = [
        _call("OUTPERFORM", False),
        _call("UNDERPERFORM", False),
        {"status": "open", "confidence": 0.9},
        {"status": "scored", "confidence": 0.7, "result": {"correct": True}},  # no outcome
    ]

    assert constant_call_baseline(rows) == {
        "sample_size": 2,
        "outperform_rate": 0.0,
        "best_call": "UNDERPERFORM",
        "hit_rate": 1.0,
    }


def test_constant_call_baseline_empty():
    assert constant_call_baseline([])["sample_size"] == 0


def test_calibration_by_model_splits_on_the_tag_oldest_window_first():
    rows = [
        _call("OUTPERFORM", True, model="gpt-5.6-terra", date="2026-08-10", confidence=0.7),
        _call("OUTPERFORM", False, model="gpt-5.6-terra", date="2026-09-01", confidence=0.7),
        _call("UNDERPERFORM", False, model="gpt-4.1-mini", date="2026-07-08", confidence=0.6),
        _call("OUTPERFORM", True, date="2026-06-12", confidence=0.8),  # pre-#113, untagged
    ]

    blocks = compute_calibration_by_model(rows)

    assert [b["model"] for b in blocks] == ["untagged", "gpt-4.1-mini", "gpt-5.6-terra"]
    terra = blocks[2]
    assert (terra["first_date"], terra["last_date"]) == ("2026-08-10", "2026-09-01")
    assert terra["sample_size"] == 2
    assert terra["win_rate"] == 0.5
    assert terra["brier_score"] == round(((0.7 - 1) ** 2 + (0.7 - 0) ** 2) / 2, 4)
    assert terra["constant_call"]["hit_rate"] == 0.5
    assert blocks[1]["constant_call"]["best_call"] == "UNDERPERFORM"


def test_calibration_by_model_skips_unresolved_rows():
    rows = [{"status": "open", "model": "gpt-5.6-terra", "confidence": 0.6}]

    assert compute_calibration_by_model(rows) == []
