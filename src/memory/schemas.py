from dataclasses import asdict, dataclass, field
from typing import Literal

MemoryType = Literal[
    "report_summary",
    "thesis",
    "trade",
    "risk_lesson",
    "macro_regime",
    "earnings_event",
    "mistake",
]


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    memory_type: MemoryType
    content: str
    date: str
    run_id: str | None = None
    symbols: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    source_type: str = ""
    source_id: str = ""
    confidence: float | None = None
    outcome: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_document_metadata(self) -> dict:
        payload = asdict(self)
        payload.pop("content")
        payload["type"] = self.memory_type
        return payload


@dataclass
class MemoryIngestionResult:
    status: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return self.created + self.updated + self.skipped

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "total_processed": self.total_processed,
        }
