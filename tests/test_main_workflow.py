from dataclasses import dataclass
from datetime import date

from src.main import build_failure_run_status, build_run_status, extract_prices
from src.models.portfolio import PortfolioSnapshot


@dataclass
class MemoryResult:
    status: str
    error: str | None = None


def test_extract_prices_filters_missing_and_invalid_prices():
    research = {
        "symbols": [
            {"symbol": "AAPL", "price": 200.0},
            {"symbol": "MSFT", "price": None},
            {"symbol": "NVDA", "price": 0},
        ]
    }

    assert extract_prices(research) == {"AAPL": 200.0}


def test_build_run_status_records_memory_warning():
    snapshot = PortfolioSnapshot(date=date.today(), cash=25000, positions=[])
    status = build_run_status(
        run_id="run_123",
        started_at="2024-06-01T12:00:00Z",
        memory_result=MemoryResult(status="unavailable", error="qdrant offline"),
        memory_context=[],
        trades=[],
        snapshot=snapshot,
    )

    assert status["run_id"] == "run_123"
    assert status["status"] == "success"
    assert status["memory_status"] == "unavailable"
    assert status["memory_error"] == "qdrant offline"
    assert status["memory_chunks"] == 0
    assert status["trades_executed"] == 0
    assert status["warnings"] == ["Memory unavailable: qdrant offline"]
    assert status["portfolio_value"] == 25000


def test_build_failure_run_status_records_failed_step_and_errors():
    snapshot = PortfolioSnapshot(date=date.today(), cash=25000, positions=[])
    status = build_failure_run_status(
        run_id="run_123",
        started_at="2024-06-01T12:00:00Z",
        failed_step="decide_trades",
        errors=["decide_trades: model unavailable"],
        warnings=["memory degraded"],
        snapshot=snapshot,
    )

    assert status["run_id"] == "run_123"
    assert status["status"] == "failed"
    assert status["failed_step"] == "decide_trades"
    assert status["errors"] == ["decide_trades: model unavailable"]
    assert status["warnings"] == ["memory degraded"]
    assert status["portfolio_value"] == 25000
