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


def test_public_exporter_writes_prediction_dashboard(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    public_dir = tmp_path / "public"
    data_dir.mkdir()
    public_dir.mkdir()
    predictions = [
        {
            "id": "best",
            "date": "2024-01-01",
            "symbol": "AAPL",
            "prediction": "AAPL will outperform SPY",
            "confidence": 0.8,
            "start_price": 100,
            "spy_start_price": 400,
            "due_date": "2024-01-31",
            "status": "scored",
            "result": {
                "symbol_return": 0.2,
                "spy_return": 0.05,
                "outperformed": True,
                "scored_date": "2024-02-01",
            },
        },
        {
            "id": "worst",
            "date": "2024-01-02",
            "symbol": "MSFT",
            "prediction": "MSFT will outperform SPY",
            "confidence": 0.7,
            "start_price": 200,
            "spy_start_price": 405,
            "due_date": "2024-02-01",
            "status": "scored",
            "result": {
                "symbol_return": -0.03,
                "spy_return": 0.04,
                "outperformed": False,
                "scored_date": "2024-02-02",
            },
        },
        {
            "id": "open",
            "date": "2024-01-03",
            "symbol": "NVDA",
            "prediction": "NVDA will outperform SPY",
            "confidence": 0.9,
            "start_price": 300,
            "spy_start_price": 410,
            "due_date": "2024-02-03",
            "status": "open",
            "result": None,
        },
    ]
    (data_dir / "predictions.jsonl").write_text(
        "\n".join(json.dumps(prediction) for prediction in predictions) + "\n"
    )
    monkeypatch.setattr("src.reporting.public_exporter.DATA_DIR", data_dir)
    monkeypatch.setattr("src.reporting.public_exporter.PUBLIC_DIR", public_dir)

    PublicExporter()._write_prediction_dashboard()

    payload = json.loads((public_dir / "predictions.json").read_text())

    assert payload["metrics"] == {
        "total": 3,
        "resolved": 2,
        "open": 1,
        "accuracy_pct": 50.0,
    }
    assert payload["best_predictions"][0]["id"] == "best"
    assert payload["best_predictions"][0]["alpha_pct"] == 15.0
    assert payload["worst_predictions"][0]["id"] == "worst"
    assert payload["worst_predictions"][0]["alpha_pct"] == -7.0
    assert payload["upcoming_predictions"][0]["id"] == "open"
