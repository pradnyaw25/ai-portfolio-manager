#!/usr/bin/env python3
"""Refresh the public memory health artifact."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reporting.public_exporter import PublicExporter


def main() -> int:
    run_status_path = Path("public/run_status.json")
    run_status = None
    if run_status_path.exists():
        run_status = json.loads(run_status_path.read_text())

    PublicExporter().write_memory_health(run_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
