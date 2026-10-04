"""Confidence calibration metrics for resolved predictions.

Given the prediction history (each with a stated ``confidence`` and, once
resolved, a binary ``correct`` outcome), compute:

* **Brier score** — mean squared error between confidence and outcome (0 is
  perfect, 0.25 is a coin flip at 0.5 confidence, 1 is confidently wrong).
* **Calibration curve** — per confidence bucket, the average predicted
  confidence vs. the observed win rate. A well-calibrated model tracks the
  diagonal (predicted ≈ actual).
* **Per-bucket hit rate** — the win rate within each confidence bucket.
* **Per-model split** — the same metrics for each model that made calls, so a
  model swap shows up as a second curve rather than a blur in the aggregate.
* **Constant-call baseline** — what "always say UNDERPERFORM" (or OUTPERFORM)
  would have scored on the same questions. A hit rate only means something
  relative to the base rate of the window it was earned in.

Pure and deterministic: same history in → same metrics out.
"""

from collections import defaultdict

# Rows that predate the ``model`` tag (#113) still count; they just get a label.
UNTAGGED_MODEL = "untagged"


def was_correct(prediction: dict) -> bool | None:
    """Whether the fund's *directional call* was right. ``None`` if unresolved.

    This is deliberately NOT ``result.outperformed``, which only says the symbol
    beat SPY. The fund predicts in both directions: an "underperform" call on a
    stock that duly lagged has ``outperformed=False`` but ``correct=True``. Reading
    ``outperformed`` as correctness inverts the outcome for every underperform
    call — 75 of the first 109 predictions — which understated published accuracy
    (41.5% vs a true 59%) and inverted the Brier score and calibration curve.

    Legacy rows predate the ``correct`` field and were all outperform bets, so they
    fall back to ``outperformed`` (matching ``PredictionScorer``'s own default).
    """
    result = prediction.get("result") or {}
    value = result.get("correct")
    if value is None:
        value = result.get("outperformed")
    return None if value is None else bool(value)


def _resolved(predictions: list[dict]) -> list[dict]:
    resolved = []
    for p in predictions:
        if p.get("status") != "scored":
            continue
        if was_correct(p) is None:
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
        outcome = 1 if was_correct(p) else 0

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


def empty_constant_call() -> dict:
    return {"sample_size": 0, "outperform_rate": None, "best_call": None, "hit_rate": None}


def constant_call_baseline(predictions: list[dict]) -> dict:
    """The best a model with no information could have done on these questions.

    Each call is "beat SPY" or "lag SPY" over a window. If 59% of the names in the
    window lagged SPY — as they did in July 2026 — then a model that said
    UNDERPERFORM every time scores 59% without reading a single headline. The
    fund's hit rate has to be read against that number, not against 50%.

    ``outperform_rate`` is the share of resolved calls whose symbol beat SPY;
    ``best_call`` is the constant answer that would have hit most often and
    ``hit_rate`` is how often. Rows without a recorded ``outperformed`` are skipped.
    """
    outcomes = [
        bool((p.get("result") or {}).get("outperformed"))
        for p in _resolved(predictions)
        if (p.get("result") or {}).get("outperformed") is not None
    ]
    n = len(outcomes)
    if n == 0:
        return empty_constant_call()
    rate = sum(outcomes) / n
    best_call, hit_rate = ("OUTPERFORM", rate) if rate >= 0.5 else ("UNDERPERFORM", 1 - rate)
    return {
        "sample_size": n,
        "outperform_rate": round(rate, 4),
        "best_call": best_call,
        "hit_rate": round(hit_rate, 4),
    }


def compute_calibration_by_model(predictions: list[dict], *, bucket_size: float = 0.1) -> list[dict]:
    """One calibration block per model that made resolved calls, oldest window first.

    Models were swapped mid-history (gpt-4.1-mini → gpt-5.6-terra on 2026-08-08),
    so the aggregate curve averages two different models over two different market
    regimes. Splitting by the ``model`` tag each prediction carries makes the swap
    visible. Each block carries its own constant-call baseline because the windows
    don't overlap and their base rates differ.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in _resolved(predictions):
        groups[str(p.get("model") or UNTAGGED_MODEL)].append(p)

    blocks = []
    for model, rows in groups.items():
        dates = sorted(str(p.get("date") or "") for p in rows)
        blocks.append(
            {
                "model": model,
                "first_date": dates[0],
                "last_date": dates[-1],
                **compute_calibration(rows, bucket_size=bucket_size),
                "constant_call": constant_call_baseline(rows),
            }
        )
    return sorted(blocks, key=lambda b: (b["first_date"], b["model"]))
