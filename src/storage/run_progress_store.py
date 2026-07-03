"""Durable, SQLite-backed record of daily-run progress for crash recovery.

The daily graph's live state (engine, market/news clients, stores) is not
serializable, so LangGraph's native checkpointer can't persist it. Instead we
persist just the *progress* of a run — which phases have completed — to SQLite.

If the process dies mid-run, ``latest_unfinished`` reports the run that never
finished; the driver re-enters it, **reusing the same run_id**. The P0-3 idempotent
stores (trades/decisions/predictions keyed by run_id) guarantee re-execution
produces no duplicates, and phases with a non-idempotent external side effect
(publishing a tweet) are skipped on resume via ``completed_phases``.
"""

import sqlite3
from pathlib import Path

from src.config import DATA_DIR
from src.utils.run_id import utc_now_iso

RUN_PROGRESS_DB = DATA_DIR / "run_progress.db"


class RunProgressStore:
    def __init__(self, path: Path | None = None):
        self.path = path or RUN_PROGRESS_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "run_id TEXT PRIMARY KEY, started_at TEXT, status TEXT, updated_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS phases ("
                "run_id TEXT, phase TEXT, PRIMARY KEY (run_id, phase))"
            )

    def start_run(self, run_id: str, started_at: str) -> None:
        """Mark a run as running (idempotent — re-entering keeps the first started_at)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, started_at, status, updated_at) "
                "VALUES (?, ?, 'running', ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status='running', updated_at=excluded.updated_at",
                (run_id, started_at, utc_now_iso()),
            )

    def mark_phase(self, run_id: str, phase: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO phases (run_id, phase) VALUES (?, ?)", (run_id, phase)
            )
            conn.execute(
                "UPDATE runs SET updated_at=? WHERE run_id=?", (utc_now_iso(), run_id)
            )

    def completed_phases(self, run_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT phase FROM phases WHERE run_id=?", (run_id,)
            ).fetchall()
        return {row[0] for row in rows}

    def phase_done(self, run_id: str, phase: str) -> bool:
        return phase in self.completed_phases(run_id)

    def finish_run(self, run_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE run_id=?",
                (status, utc_now_iso(), run_id),
            )

    def latest_unfinished(self) -> dict | None:
        """The most recent run still marked ``running`` (a process that died mid-run)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, started_at FROM runs WHERE status='running' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return {"run_id": row[0], "started_at": row[1]} if row else None
