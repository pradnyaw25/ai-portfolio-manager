"""Variety engine: which tickers were tweeted recently, so the fund doesn't lead
with the same name day after day (roadmap W02).

The social-post log (``data/social_posts.jsonl``) already records every tweet's text
and timestamp, so the recently-featured symbols can be read straight from it — no
extra bookkeeping. A symbol tweeted inside the cooldown window is "on cooldown" and
gets deprioritized by callers when they choose what to tweet about.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from src.config import BENCHMARK_SYMBOLS, TWEET_SYMBOL_COOLDOWN_DAYS, WATCHLIST
from src.social.twitter import SOCIAL_POSTS_FILE

_BENCHMARKS = {s.upper() for s in BENCHMARK_SYMBOLS}
# The fund's tickers, benchmarks excluded (SPY/QQQ are references, not the subject).
_COOLDOWN_UNIVERSE = {s.upper() for s in WATCHLIST} - _BENCHMARKS


def _parse_ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def load_recent_posts(path: Path = SOCIAL_POSTS_FILE) -> list[dict]:
    if not path.exists():
        return []
    posts = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            posts.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return posts


def _symbols_in(text: str, universe: set[str]) -> set[str]:
    """Tickers from ``universe`` that appear in ``text`` — bare (AAPL) or cashtagged
    ($AAPL), as whole words."""
    found = set()
    for sym in universe:
        if re.search(rf"(?<!\w)\$?{re.escape(sym)}(?!\w)", text):
            found.add(sym)
    return found


def symbols_in_text(text: str, universe: set[str] | None = None) -> set[str]:
    """The fund's tickers named in ``text`` (defaults to the watchlist universe).
    Used to keep a second tweet off the name the first one already covered."""
    return _symbols_in(str(text or ""), universe if universe is not None else _COOLDOWN_UNIVERSE)


def recent_tweet_symbols(
    posts: list[dict],
    *,
    within_days: int = TWEET_SYMBOL_COOLDOWN_DAYS,
    now: datetime,
    universe: set[str] | None = None,
) -> set[str]:
    """Symbols featured in a tweet that actually went out within the cooldown window.

    Only counts posts that posted (or would have, in dry-run) — a failed/blocked post
    never reached the feed, so it shouldn't suppress a name. ``now`` is passed in so
    the result is deterministic and testable.
    """
    universe = universe if universe is not None else _COOLDOWN_UNIVERSE
    cutoff = now - timedelta(days=within_days)
    on_cooldown: set[str] = set()
    for post in posts:
        if post.get("status") not in ("posted", "dry_run"):
            continue
        ts = _parse_ts(post.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        on_cooldown |= _symbols_in(str(post.get("text", "")), universe)
    return on_cooldown
