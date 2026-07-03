"""Confidence calibration metrics for resolved predictions.

Given the prediction history (each with a stated ``confidence`` and, once
resolved, a binary ``outperformed`` outcome), compute:

* **Brier score** — mean squared error between confidence and outcome (0 is
  perfect, 0.25 is a coin flip at 0.5 confidence, 1 is confidently wrong).
* **Calibration curve** — per confidence bucket, the average predicted
  confidence vs. the observed win rate. A well-calibrated model tracks the
  diagonal (predicted ≈ actual).
* **Per-bucket hit rate** — the win rate within each confidence bucket.

Pure and deterministic: same history in → same metrics out.
"""

from collections import defaultdict


def _resolved(predictions: list[dict]) -> list[dict]:
    resolved = []
    for p in predictions:
        if p.get("status") != "scored":
            continue
        result = p.get("result") or {}
        if result.get("outperformed") is None:
            continue
        resolved.append(p)
    return resolved


def _bucket_index(confidence: float, bucket_size: float, num_buckets: int) -> int:
    index = int(confidence / bucket_size)
    return max(0, min(index, num_buckets - 1))  # confidence == 1.0 → last bucket


def empty_calibration() -> dict:
    return {
        "sample_size": 0,
        "brier_score": None,
        "mean_confidence": None,
        "win_rate": None,
        "buckets": [],
    }


def compute_calibration(predictions: list[dict], *, bucket_size: float = 0.1) -> dict:
    """Compute Brier score and a bucketed calibration curve over resolved predictions."""
    resolved = _resolved(predictions)
    n = len(resolved)
    if n == 0:
        return empty_calibration()

    num_buckets = int(round(1 / bucket_size))
    bucket_conf: dict[int, float] = defaultdict(float)
    bucket_wins: dict[int, int] = defaultdict(int)
    bucket_count: dict[int, int] = defaultdict(int)

    total_brier = 0.0
    total_conf = 0.0
    total_wins = 0

    for p in resolved:
        confidence = float(p.get("confidence", 0.0))
        outcome = 1 if p["result"]["outperformed"] else 0

        total_brier += (confidence - outcome) ** 2
        total_conf += confidence
        total_wins += outcome

        index = _bucket_index(confidence, bucket_size, num_buckets)
        bucket_conf[index] += confidence
        bucket_wins[index] += outcome
        bucket_count[index] += 1

    buckets = []
    for index in range(num_buckets):
        count = bucket_count[index]
        if count == 0:
            continue
        buckets.append(
            {
                "lower": round(index * bucket_size, 2),
                "upper": round((index + 1) * bucket_size, 2),
                "predicted": round(bucket_conf[index] / count, 4),
                "actual": round(bucket_wins[index] / count, 4),
                "count": count,
            }
        )

    return {
        "sample_size": n,
        "brier_score": round(total_brier / n, 4),
        "mean_confidence": round(total_conf / n, 4),
        "win_rate": round(total_wins / n, 4),
        "buckets": buckets,
    }
