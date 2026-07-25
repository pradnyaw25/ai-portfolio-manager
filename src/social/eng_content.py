"""Weekend engineering content — pick and render one curated build-in-public note.

The notes live in ``config/engineering_notes.yaml`` (hand-curated, grounded in real
repo work — see that file). Selection is least-recently-used: a note that has never
posted goes first, otherwise the one posted longest ago, so the whole pool cycles
before anything repeats. "When did this note last post" is read straight from the
social-post log by matching the note's text, so there's no separate bookkeeping.
"""

from pathlib import Path

import yaml

from src.config import CONFIG_DIR

NOTES_PATH = CONFIG_DIR / "engineering_notes.yaml"
ENGINEERING_URL = "glasshousefund.com/engineering.html"
_TWEET_LIMIT = 280
# Enough of a note's opening to identify it in the post log without being brittle.
_MATCH_PREFIX = 40


def _norm(text: str) -> str:
    """Collapse whitespace so a YAML-folded note matches its posted single-line form."""
    return " ".join(str(text or "").split())


def load_notes(path: Path = NOTES_PATH) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    notes = data.get("notes") or []
    valid = [n for n in notes if isinstance(n, dict) and n.get("id") and _norm(n.get("text"))]
    ids = [n["id"] for n in valid]
    if len(ids) != len(set(ids)):
        raise ValueError("engineering_notes.yaml has duplicate note ids")
    return valid


def _last_posted_at(note: dict, posts: list[dict]) -> str | None:
    """The most recent time this note went out (posted or dry-run), or None."""
    prefix = _norm(note["text"])[:_MATCH_PREFIX]
    stamps = [
        p.get("created_at") or ""
        for p in posts
        if p.get("status") in ("posted", "dry_run") and prefix and prefix in _norm(p.get("text", ""))
    ]
    return max(stamps) if stamps else None


def select_note(notes: list[dict], posts: list[dict]) -> dict | None:
    """Least-recently-used: never-posted notes first (in pool order), then oldest."""
    if not notes:
        return None

    def key(indexed):
        index, note = indexed
        last = _last_posted_at(note, posts)
        # (has ever posted, when, pool order) — never-posted (False) sorts first;
        # among posted, oldest timestamp first; pool order is the stable tiebreak.
        return (last is not None, last or "", index)

    return min(enumerate(notes), key=key)[1]


def render_note_tweet(note: dict) -> str:
    """The note's text with the engineering-page link appended, within the tweet limit
    (the body is trimmed if needed; the link is never cut)."""
    text = _norm(note["text"])
    room = _TWEET_LIMIT - len(ENGINEERING_URL) - 1
    return f"{text[:room].rstrip()}\n{ENGINEERING_URL}"
