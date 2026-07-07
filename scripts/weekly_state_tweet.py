#!/usr/bin/env python3
"""Weekly "state of the fund" tweet: identity + honest performance vs benchmarks,
with a performance chart image. Runs on a weekly cron, separate from the daily recap.

Flow: gather inception-to-date facts -> render the perf chart PNG -> generate the
tweet (cheap tier) -> grounding gate (block ungrounded claims) -> publish with media.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json

from src.agents.state_of_fund import gather_state_facts, generate_state_tweet
from src.config import validate_config
from src.reporting.perf_chart import render_performance_chart_from_files
from src.reporting.public_exporter import PUBLIC_DIR
from src.scoring.grounding import check_grounding
from src.social.twitter import publish_tweet
from src.utils.logger import get_logger
from src.utils.run_id import create_run_id

logger = get_logger(__name__)


def _export(text: str, chart: bytes | None, facts: dict, grounding: dict, publish: dict) -> None:
    PUBLIC_DIR.mkdir(exist_ok=True)
    if chart:
        (PUBLIC_DIR / "perf_chart.png").write_bytes(chart)
    (PUBLIC_DIR / "state_tweet.json").write_text(
        json.dumps({"text": text, "facts": facts, "grounding": grounding, "publish": publish}, indent=2)
    )


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
    facts = gather_state_facts()
    if not facts.get("enough_data"):
        logger.info("Not enough history for a state-of-fund tweet (days=%s) — skipping.", facts.get("days"))
        return 0

    chart = render_performance_chart_from_files()
    text = generate_state_tweet(facts)
    logger.info("State tweet: %s", text)

    grounding = check_grounding(
        {"market_summary": text},
        research={"facts": facts},
        memory=[],
        portfolio={"cash_pct": facts.get("cash_pct"), "value": facts.get("portfolio_value")},
    )
    if grounding.status == "flagged":
        logger.warning("State tweet blocked by grounding: %s", grounding.issues)
        _export(text, chart, facts, grounding.to_dict(), {"status": "blocked_grounding", "posted": False})
        print("State tweet blocked by grounding check — not published.")
        return 0

    result = publish_tweet(text, media=chart, run_id=create_run_id(), dry_run=args.dry_run)
    _export(text, chart, facts, grounding.to_dict(), result.to_dict())
    print(f"State tweet {result.status} (posted={result.posted}) {result.tweet_url or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
