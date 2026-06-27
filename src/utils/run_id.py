from datetime import UTC, datetime
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_run_id(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    timestamp = current.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{timestamp}_{uuid4().hex[:8]}"
