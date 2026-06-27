from datetime import date

from src.models.trade import Trade, TradeAction
from src.storage import trade_store
from src.storage.trade_store import TRADE_FIELDS, TradeStore


def test_trade_store_saves_run_id(tmp_path, monkeypatch):
    trades_file = tmp_path / "trades.csv"
    monkeypatch.setattr(trade_store, "TRADES_FILE", trades_file)

    TradeStore().save(
        Trade(
            date=date(2024, 6, 1),
            symbol="AAPL",
            action=TradeAction.BUY,
            shares=10,
            price=180.0,
            reasoning="test",
            run_id="run_123",
        )
    )

    rows = TradeStore().load_all()

    assert rows[0]["run_id"] == "run_123"
    assert rows[0]["symbol"] == "AAPL"


def test_trade_store_upgrades_legacy_csv_header(tmp_path, monkeypatch):
    trades_file = tmp_path / "trades.csv"
    trades_file.write_text(
        "date,symbol,action,shares,price,total,reasoning\n"
        "2024-06-01,AAPL,BUY,10,180.00,1800.00,test\n"
    )
    monkeypatch.setattr(trade_store, "TRADES_FILE", trades_file)

    TradeStore().save(
        Trade(
            date=date(2024, 6, 2),
            symbol="MSFT",
            action=TradeAction.SELL,
            shares=2,
            price=400.0,
            reasoning="trim",
            run_id="run_456",
        )
    )

    header = trades_file.read_text().splitlines()[0].split(",")
    rows = TradeStore().load_all()

    assert header == TRADE_FIELDS
    assert rows[0]["run_id"] == ""
    assert rows[1]["run_id"] == "run_456"
