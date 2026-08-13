#!/usr/bin/env python3
"""Did the fund actually run and succeed today?

This exists because of two August 2026 incidents that both looked like success:

* 2026-08-05 — the cycle timed out in ``decide_trades`` and the job reported green,
  because ``daily_run.py`` discarded the run object and exited 0. Fixed in #92, but
  that only made the failure *visible*, not *noticed*.
* 2026-08-06 — a ~103-minute-late cron left the morning run queued when the afternoon
  run entered the same concurrency group, so it was cancelled outright and the fund
  lost a whole trading day. Fixed in #92.

Both were found days later, by hand. Nothing watched. This check is the watcher, and
it runs as a **separate scheduled workflow** on purpose: a run that is cancelled
before its first step writes no ``run_history`` row at all, so the daily run cannot
detect its own absence. Only an independent observer can.

Exits 0 when healthy or when nothing was expected (weekend / market holiday), 1 when
the fund was supposed to run and either didn't or failed.
"""

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Inlined rather than imported from src: this watchdog must run on a bare checkout with
# no third-party dependencies installed — importing src.config pulls in PyYAML, which
# is exactly the "fails for reasons of its own" trap the workflow warns against (it was
# the actual cause of every check failing). These are stable facts (data lives in
# data/, the NYSE opens 9:30 ET); keep them in step with src.config.DATA_DIR and
# src.utils.market_hours.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)

RUN_HISTORY = DATA_DIR / "run_history.jsonl"

# NYSE full-day closures. Only weekdays are listed — a weekend is already handled.
#
# Kept as a literal rather than a dependency: the check must not need network access
# or a new package to decide whether to alarm. If this list goes stale the failure
# mode is one benign false alarm on an unlisted holiday, and the message below says
# exactly how to fix it. Extend before each January.
MARKET_HOLIDAYS = {
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in MARKET_HOLIDAYS


def target_day(now: datetime) -> date:
    """Which trading day this invocation is judging.

    Normally today. But this workflow is itself scheduled, and GitHub's scheduler on
    this repo has fired up to ~4h45m late — enough to push a 22:15 UTC check past
    midnight in market time, where "today" would be a day the fund has not run yet and
    every check would false-alarm. So if we wake before the opening bell, we are the
    tail of the previous day's check and that is the day to judge.
    """
    current = now.astimezone(MARKET_TZ)
    day = current.date()
    if current.time() < MARKET_OPEN:
        day -= timedelta(days=1)
    # Step back over a weekend or holiday to the last day the fund should have run.
    for _ in range(7):
        if is_trading_day(day):
            return day
        day -= timedelta(days=1)
    return day


def load_runs(path: Path | None = None) -> list[dict]:
    path = path or RUN_HISTORY
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn write shouldn't mask a real alert
    return out


def _started_on(run: dict) -> date | None:
    """The run's start date in market time, or None if unparseable."""
    raw = str(run.get("started_at") or "")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp.date()
    return stamp.astimezone(MARKET_TZ).date()


def check(runs: list[dict], today: date) -> tuple[bool, str]:
    """Return (healthy, message).

    Health is judged on the day's LAST run, not on whether any run failed. The two
    cron slots exist so the second can recover the first: on 2026-08-05 the morning
    run timed out and the afternoon run succeeded, and the fund did trade that day.
    Paging on a recovered failure would be noise, and an alert people learn to ignore
    is worse than no alert. Recovered failures are still named in the OK message so
    they don't vanish — the individual run is already red in CI from #92.
    """
    if not is_trading_day(today):
        return True, f"{today} is not a trading day — nothing expected."

    todays = [r for r in runs if _started_on(r) == today]

    if not todays:
        return False, (
            f"NO RUN RECORDED for {today}, a trading day. The cycle never started, or "
            f"was cancelled before its first step (a cancelled run writes no "
            f"run_history row — this is the 2026-08-06 failure). Check the Actions tab "
            f"for a cancelled or missing 'Daily Portfolio Run'. "
            f"If {today} was a market holiday, add it to MARKET_HOLIDAYS in "
            f"scripts/check_run_health.py."
        )

    latest = max(todays, key=lambda r: str(r.get("started_at") or ""))
    status = str(latest.get("status") or "unknown")
    if status != "success":
        errors = latest.get("errors") or []
        detail = "; ".join(str(e) for e in errors) if errors else "no error detail recorded"
        return False, (
            f"RUN FAILED on {today} (run_id={latest.get('run_id')}, status={status}): "
            f"{detail}. This is the 2026-08-05 failure mode."
        )

    failed_earlier = [r for r in todays if str(r.get("status") or "") != "success"]
    recovered = (
        f" NOTE: {len(failed_earlier)} earlier run(s) failed today and were recovered "
        f"by this one — not paging, but worth a look."
        if failed_earlier
        else ""
    )
    return True, (
        f"OK — {len(todays)} run(s) on {today}, latest "
        f"{latest.get('run_id')} succeeded at {latest.get('completed_at')}.{recovered}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help="Trading day to check, YYYY-MM-DD. Defaults to today in America/New_York.",
    )
    args = parser.parse_args(argv)

    today = (
        date.fromisoformat(args.date)
        if args.date
        else target_day(datetime.now(MARKET_TZ))
    )
    healthy, message = check(load_runs(), today)

    if healthy:
        print(message)
        return 0

    # ::error:: surfaces in the Actions summary and the failure email.
    print(f"::error::{message}", file=sys.stderr)
    print(message)
    return 1


if __name__ == "__main__":
    sys.exit(main())
