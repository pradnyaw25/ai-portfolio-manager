"""Durable, append-with-upsert store of every run's final status.

Keeps a JSONL row per run (keyed by run_id) so run history survives across runs
— unlike ``public/run_status.json`` which only holds the latest run.
"""

import json
from pathlib import Path

from src.config import RUN_HISTORY_LOG


class RunHistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or RUN_HISTORY_LOG

    def record(self, run_status: dict) -> None:
        """Upsert a run's status by run_id (re-running a run_id replaces its row)."""
        if not run_status:
            return
        run_id = run_status.get("run_id")
        rows = [r for r in self.load() if r.get("run_id") != run_id]
        rows.append(run_status)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
