from pathlib import Path
from src.config import REPORTS_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ReportStore:
    def list_reports(self, extension: str = ".md") -> list[Path]:
        return sorted(REPORTS_DIR.glob(f"report_*{extension}"), reverse=True)

    def get_latest(self, extension: str = ".md") -> str | None:
        reports = self.list_reports(extension)
        if not reports:
            return None
        return reports[0].read_text()

    def get_by_date(self, date_str: str, extension: str = ".md") -> str | None:
        filepath = REPORTS_DIR / f"report_{date_str}{extension}"
        if filepath.exists():
            return filepath.read_text()
        return None
