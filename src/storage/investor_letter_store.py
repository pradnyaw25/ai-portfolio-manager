"""Durable store of weekly investor letters, upserted by week (idempotent).

Keeps one JSONL row per ``week_end`` so re-running a week overwrites its letter
instead of appending a duplicate — mirrors ``run_history_store``.
"""

import json
from pathlib import Path

from src.config import DATA_DIR

INVESTOR_LETTERS_FILE = DATA_DIR / "investor_letters.jsonl"


class InvestorLetterStore:
    def __init__(self, path: Path | None = None):
        self.path = path or INVESTOR_LETTERS_FILE

    def record(self, letter: dict) -> None:
        """Upsert a letter by ``week_end`` (re-running a week replaces its row)."""
        week_end = letter.get("week_end")
        rows = [r for r in self.load() if r.get("week_end") != week_end]
        rows.append(letter)
        rows.sort(key=lambda r: str(r.get("week_end", "")))
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
