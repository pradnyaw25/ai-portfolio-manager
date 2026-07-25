#!/usr/bin/env python3
"""Weekend engineering-content tweet — one curated build-in-public note.

Runs on a weekend cron (markets closed), picks the least-recently-used note from
``config/engineering_notes.yaml``, attaches the performance chart if the note asks
for it, and publishes. Curated text, so no LLM call and no grounding gate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse

from src.config import validate_config
from src.reporting.perf_chart import render_performance_chart_from_files
from src.social.cooldown import load_recent_posts
from src.social.eng_content import load_notes, render_note_tweet, select_note
from src.social.twitter import publish_tweet
from src.utils.logger import get_logger
from src.utils.run_id import create_run_id


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate everything but never publish, regardless of POST_TWEET.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    validate_config()
    logger = get_logger(__name__)

    notes = load_notes()
    if not notes:
        logger.info("No engineering notes configured — skipping.")
        return 0

    note = select_note(notes, load_recent_posts())
    text = render_note_tweet(note)
    logger.info("Engineering note '%s': %s", note["id"], text)

    chart = render_performance_chart_from_files() if note.get("chart") == "performance" else None

    result = publish_tweet(text, media=chart, run_id=create_run_id(), dry_run=args.dry_run)
    print(f"Engineering note '{note['id']}' {result.status} (posted={result.posted}) {result.tweet_url or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
