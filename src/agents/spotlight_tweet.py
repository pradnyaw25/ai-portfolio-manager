"""Call spotlight — a second daily tweet that features one high-conviction
directional call in depth: the fund's view, why, and the catalyst behind it.

Posts on the afternoon run (the morning run carries the receipts tweet), so the feed
gets a distinct second post spread across the day rather than two at once. The name
is chosen for freshness via the cooldown engine and excludes whatever the forward
tweet already led with, so the two daily tweets never cover the same stock.

Deterministic template: the conviction, direction, and thesis are the fund's own
recorded outputs, so there's nothing for a model to invent.
"""

import re

from src.config import SPOTLIGHT_MIN_CONFIDENCE

_SITE = "glasshousefund.com"
_TWEET_LIMIT = 280
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _confidence(call: dict) -> float:
    try:
        return float(call.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _pick_call(
    calls: list[dict],
    *,
    exclude: set[str],
    cooldown: set[str],
    min_confidence: float,
) -> dict | None:
    """The call to spotlight: highest conviction that clears the floor and isn't the
    forward tweet's name, preferring a symbol not recently tweeted."""
    eligible = [
        c
        for c in calls
        if str(c.get("symbol", "")).upper() not in exclude
        and _confidence(c) >= min_confidence
    ]
    if not eligible:
        return None
    # Fresh names first, then by conviction.
    eligible.sort(key=lambda c: (str(c.get("symbol", "")).upper() in cooldown, -_confidence(c)))
    return eligible[0]


def _catalyst(symbol: str, research: dict) -> str:
    news = (research.get("symbol_news") or {}).get(symbol) or []
    for article in news:
        title = str(article.get("title", "")).strip()
        if title:
            return title
    return ""


def build_spotlight_tweet(
    calls: list[dict],
    research: dict | None = None,
    *,
    exclude: set[str] | None = None,
    cooldown: set[str] | None = None,
    min_confidence: float = SPOTLIGHT_MIN_CONFIDENCE,
) -> str | None:
    """A spotlight tweet on one high-conviction call, or None if none qualifies."""
    call = _pick_call(
        calls or [],
        exclude={s.upper() for s in (exclude or set())},
        cooldown={s.upper() for s in (cooldown or set())},
        min_confidence=min_confidence,
    )
    if call is None:
        return None

    symbol = str(call.get("symbol", "")).upper()
    verb = "lag" if str(call.get("direction") or "").upper() == "UNDERPERFORM" else "beat"
    conf = f"{_confidence(call) * 100:.0f}%"
    tag = f"${symbol}" if _TICKER_RE.match(symbol) else symbol

    header = f"Spotlight: {tag} — the fund's {conf} call to {verb} the S&P 500 over the next month."
    thesis = str(call.get("thesis") or "").strip()
    catalyst = _catalyst(symbol, research or {})

    link = f"{_SITE}/symbols/{symbol}.html" if _TICKER_RE.match(symbol) else f"{_SITE}/dashboard.html"

    body_lines = [header]
    if thesis:
        body_lines.append(thesis)
    if catalyst:
        body_lines.append(f"Catalyst: {catalyst}")

    # Assemble within the tweet limit, keeping the link intact: add thesis then
    # catalyst only while they fit above the link line.
    room = _TWEET_LIMIT - len(link) - 1
    body = header
    for extra in body_lines[1:]:
        candidate = f"{body}\n{extra}"
        if len(candidate) <= room:
            body = candidate
        else:
            break
    return f"{body[:room].rstrip()}\n{link}"
