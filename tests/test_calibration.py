from src.scoring.calibration import compute_calibration, empty_calibration


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
