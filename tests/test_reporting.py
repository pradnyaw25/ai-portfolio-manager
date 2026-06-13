import json
from datetime import date
from datetime import datetime

from src.models.portfolio import PortfolioSnapshot, Position
from src.models.trade import Trade, TradeAction
from src.models.prediction import PortfolioDecision, Outlook
from src.reporting.markdown_report import MarkdownReportGenerator
from src.reporting.public_exporter import PublicExporter


def test_markdown_report_generation():
    portfolio = PortfolioSnapshot(
        date=date(2024, 6, 1),
        cash=50000,
        positions=[
            Position(symbol="AAPL", shares=10, avg_cost=170.0, current_price=180.0),
            Position(symbol="GOOGL", shares=5, avg_cost=140.0, current_price=145.0),
        ],
    )
    trades = [
        Trade(date=date(2024, 6, 1), symbol="AAPL", action=TradeAction.BUY, shares=10, price=180.0, reasoning="Strong earnings"),
    ]
    decision = PortfolioDecision(
        reasoning="Market looks strong",
        outlook=Outlook.BULLISH,
        risk_assessment="Moderate risk",
    )

    gen = MarkdownReportGenerator()
    report = gen._build_report(portfolio, trades, {}, decision)

    assert "Portfolio Report" in report
    assert "AAPL" in report
    assert "GOOGL" in report
    assert "$50,000.00" in report
    assert "BULLISH" in report
    assert "Strong earnings" in report


def test_report_with_no_trades():
    portfolio = PortfolioSnapshot(date=date(2024, 6, 1), cash=100000, positions=[])
    decision = PortfolioDecision(reasoning="Holding steady", outlook=Outlook.NEUTRAL, risk_assessment="Low")

    gen = MarkdownReportGenerator()
    report = gen._build_report(portfolio, [], {}, decision)

    assert "No trades executed today" in report


def test_public_exporter_writes_site_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporting.public_exporter.PUBLIC_DIR", tmp_path)

    PublicExporter()._write_site_meta()

    payload = json.loads((tmp_path / "site_meta.json").read_text())

    assert payload["updated_at"].endswith("Z")
    datetime.fromisoformat(payload["updated_at"].replace("Z", "+00:00"))
