#!/usr/bin/env python3
"""Run the daily portfolio management cycle through LangGraph.

``--resume`` re-enters the most recent run a prior process left unfinished
(reusing its run_id); idempotent stores dedupe any re-executed writes.

Exits non-zero when the cycle records errors. The graph already swallows a failed
step so the run still journals and the site still publishes, which meant a run that
never reached a trading decision looked identical to a clean one from the outside —
CI stayed green while the fund sat out the day. The exit code is what makes that
visible; the caller is expected to commit the audit trail first and fail afterwards.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workflows.daily_graph import run_daily_cycle_graph

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the most recent unfinished run instead of starting a new one.",
    )
    args = parser.parse_args(argv)
    run = run_daily_cycle_graph(resume=args.resume)

    if run.errors:
        print(
            f"Daily cycle failed at {run.failed_step or 'unknown step'}: "
            + "; ".join(run.errors),
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
