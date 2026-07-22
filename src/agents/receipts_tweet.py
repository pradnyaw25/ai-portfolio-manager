"""Receipts tweets — the fund grading its own past predictions.

When a directional call resolves, this posts the scorecard: what the fund said, at
what confidence, and whether it was right, with the running track record. It's the
account's differentiated content — a dated, scored record instead of another forward
guess — and it's the launch thesis showing up in the feed.

Deterministic and template-based on purpose: the numbers come straight from the
scorer, so there is nothing for a model to get wrong (and nothing to ground-check).
"""

import re

from src.scoring.calibration import was_correct

PREDICTIONS_URL = "glasshousefund.com/predictions.html"

# A plain equity ticker eligible for a cashtag.
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _pct(value, *, signed: bool = True) -> str:
    try:
        v = float(value) * 100
    except (TypeError, ValueError):
        return "?"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _direction(prediction: dict) -> str:
    """OUTPERFORM or UNDERPERFORM — from the field, else parsed from the call text."""
    raw = str(prediction.get("direction") or "").upper()
    if raw in ("OUTPERFORM", "UNDERPERFORM"):
        return raw
    return "UNDERPERFORM" if "underperform" in str(prediction.get("prediction", "")).lower() else "OUTPERFORM"


def _horizon_days(prediction: dict) -> int | None:
    days = prediction.get("horizon_days")
    if isinstance(days, int) and days > 0:
        return days
    match = re.search(r"over\s+(\d+)\s+days?", str(prediction.get("prediction", "")), re.I)
    return int(match.group(1)) if match else None


def _horizon_phrase(prediction: dict) -> str:
    days = _horizon_days(prediction)
    return f"{days}d ago" if days else "Earlier"


def _outcome_mark(prediction: dict) -> str:
    return "✓" if was_correct(prediction) else "✗"


def _record_line(record: dict) -> str:
    total = record.get("total") or 0
    correct = record.get("correct") or 0
    if not total:
        return ""
    pct = round(correct / total * 100)
    return f"Track record: {correct}/{total} calls right ({pct}%)."


def _one_line(prediction: dict) -> str:
    """A single resolved call as one plain-ticker line: '✓ NVDA lagged the S&P as
    called (−3.1% vs +0.8%)'."""
    result = prediction.get("result") or {}
    sym = str(prediction.get("symbol", "?")).upper()
    underperform = _direction(prediction) == "UNDERPERFORM"
    verb = "lag" if underperform else "beat"
    right = was_correct(prediction)
    sym_ret = _pct(result.get("symbol_return"))
    spy_ret = _pct(result.get("spy_return"))
    if right:
        past = "lagged" if underperform else "beat"
        return f"{_outcome_mark(prediction)} {sym} {past} the S&P as called ({sym_ret} vs {spy_ret})"
    return f"{_outcome_mark(prediction)} {sym}: called it to {verb} the S&P, it didn't ({sym_ret} vs {spy_ret})"


def _cashtag_first_symbol(text: str, symbol: str) -> str:
    if not _TICKER_RE.match(symbol):
        return text
    if re.search(rf"\${re.escape(symbol)}(?![\w])", text):
        return text
    return re.sub(rf"(?<![\w$]){re.escape(symbol)}(?![\w])", f"${symbol}", text, count=1)


def build_receipts_tweet(scored: list[dict], record: dict) -> str | None:
    """A scorecard tweet for the predictions that resolved this run, or None if none.

    ``scored`` is the freshly-resolved predictions (each with a ``result``); ``record``
    is the running tally ``{"total": int, "correct": int}`` over all scored calls."""
    resolved = [p for p in (scored or []) if p.get("result")]
    if not resolved:
        return None

    record_line = _record_line(record)
    # Lead with the sharpest (highest-confidence) resolved call.
    resolved.sort(key=lambda p: p.get("confidence") or 0, reverse=True)

    if len(resolved) == 1:
        p = resolved[0]
        result = p.get("result") or {}
        sym = str(p.get("symbol", "?")).upper()
        underperform = _direction(p) == "UNDERPERFORM"
        verb = "lag" if underperform else "beat"
        conf = f"{(p.get('confidence') or 0) * 100:.0f}% conviction"
        outcome = "✓ Right." if was_correct(p) else "✗ Missed."
        header = (
            f"Receipt: {_horizon_phrase(p)} I called {sym} to {verb} the S&P 500 ({conf}).\n"
            f"Result: {sym} {_pct(result.get('symbol_return'))} vs SPY "
            f"{_pct(result.get('spy_return'))} — {outcome}"
        )
        body = _cashtag_first_symbol(header, sym)
    else:
        wins = sum(1 for p in resolved if was_correct(p))
        lead = _one_line(resolved[0])
        second = _one_line(resolved[1])
        extra = len(resolved) - 2
        more = f"\n+{extra} more scored." if extra > 0 else ""
        body = (
            f"Prediction results ({wins}/{len(resolved)} right today):\n"
            f"{lead}\n{second}{more}"
        )

    parts = [body]
    if record_line:
        parts.append(record_line)
    parts.append(PREDICTIONS_URL)
    return "\n".join(parts)[:280]
