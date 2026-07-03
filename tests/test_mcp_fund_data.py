"""P5-1: read-only MCP query functions over the fund's stores."""

from datetime import date

from mcp_server import fund_data
from src.models.portfolio import Position, PortfolioSnapshot


class FakePortfolioStore:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def load(self):
        return self._snapshot


class FakeListStore:
    def __init__(self, rows):
        self._rows = rows

    def load(self):
        return self._rows

    def load_all(self):
        return self._rows


def test_get_holdings_reports_positions_and_pnl():
    snapshot = PortfolioSnapshot(
        date=date(2026, 6, 30),
        cash=100_000,
        positions=[Position("NVDA", 100, 100.0, 150.0)],
    )
    result = fund_data.get_holdings(store=FakePortfolioStore(snapshot))
    assert result["status"] == "ok"
    assert result["total_value"] == 115_000.0  # 100k cash + 100*150
    pos = result["positions"][0]
    assert pos["symbol"] == "NVDA"
    assert pos["unrealized_pnl"] == 5_000.0
    assert pos["return_pct"] == 0.5


def test_get_holdings_handles_missing_state():
    result = fund_data.get_holdings(store=FakePortfolioStore(None))
    assert result["status"] == "no_portfolio_state"
    assert result["positions"] == []


def test_performance_history_newest_first_and_limited():
    rows = [
        {"run_id": "r1", "started_at": "2026-06-01T00:00:00Z", "portfolio_value": 100},
        {"run_id": "r2", "started_at": "2026-06-03T00:00:00Z", "portfolio_value": 200,
         "llm": {"cost_usd": 0.02}},
        {"run_id": "r3", "started_at": "2026-06-02T00:00:00Z", "portfolio_value": 150},
    ]
    result = fund_data.get_performance_history(limit=2, store=FakeListStore(rows))
    assert [r["run_id"] for r in result] == ["r2", "r3"]
    assert result[0]["llm_cost_usd"] == 0.02


_TRADES = [
    {"run_id": "r1", "date": "2026-06-10", "symbol": "NVDA", "action": "BUY", "shares": "10"},
    {"run_id": "r2", "date": "2026-06-20", "symbol": "NVDA", "action": "SELL", "shares": "10"},
    {"run_id": "r3", "date": "2026-07-01", "symbol": "AAPL", "action": "BUY", "shares": "5"},
]


def test_list_trades_filters_by_symbol_action_and_range():
    store = FakeListStore(_TRADES)
    sells = fund_data.list_trades(symbol="nvda", action="sell", store=store)
    assert [t["run_id"] for t in sells] == ["r2"]

    june = fund_data.list_trades(symbol="NVDA", since="2026-06-01", until="2026-06-30", store=store)
    assert {t["run_id"] for t in june} == {"r1", "r2"}
    # Newest first.
    assert [t["date"] for t in june] == ["2026-06-20", "2026-06-10"]


_DECISIONS = [
    {
        "run_id": "r2", "date": "2026-06-20",
        "executed_trades": [{"symbol": "NVDA", "action": "SELL", "shares": 10}],
        "risk_events": [{"symbol": "NVDA", "origin": "system", "risk_event": "stop_loss"}],
        "raw_decision": {
            "outlook": "BEARISH", "summary": "Trim NVDA on risk breach.",
            "debate": {"bull": {"thesis": "up"}, "bear": {"thesis": "down"}, "risk": {"thesis": "hot"}},
            "bear_case_response": "Acknowledged; cutting exposure.",
        },
    },
    {
        "run_id": "r3", "date": "2026-07-01",
        "executed_trades": [{"symbol": "AAPL", "action": "BUY", "shares": 5}],
        "raw_decision": {"outlook": "NEUTRAL", "summary": "Add AAPL."},
    },
]


def test_list_decisions_filters_by_symbol():
    store = FakeListStore(_DECISIONS)
    nvda = fund_data.list_decisions(symbol="NVDA", store=store)
    assert [d["run_id"] for d in nvda] == ["r2"]
    assert nvda[0]["has_debate"] is True


def test_get_decision_by_run_id_returns_full_detail():
    detail = fund_data.get_decision(run_id="r2", store=FakeListStore(_DECISIONS))
    assert detail["status"] == "ok"
    assert detail["outlook"] == "BEARISH"
    assert detail["risk_events"][0]["origin"] == "system"
    assert detail["bear_case_response"].startswith("Acknowledged")


def test_get_decision_not_found():
    assert fund_data.get_decision(run_id="nope", store=FakeListStore(_DECISIONS))["status"] == "not_found"


def test_get_debate_returns_transcript_or_no_debate():
    store = FakeListStore(_DECISIONS)
    debate = fund_data.get_debate(run_id="r2", store=store)
    assert debate["status"] == "ok"
    assert set(debate["debate"]) == {"bull", "bear", "risk"}

    none = fund_data.get_debate(run_id="r3", store=store)
    assert none["status"] == "no_debate"


def test_search_memory_maps_results_and_degrades(monkeypatch):
    from src.memory import retriever

    def fake_retrieve(*, query, k):
        return retriever.MemoryRetrievalResult(
            chunks=[{"id": "thesis:1", "type": "thesis", "content": "NVDA AI thesis",
                     "symbols": ["NVDA"], "date": "2026-06-01", "source_type": "decision"}],
            grouped=retriever.empty_grouped_memory(),
            status="ok",
        )

    monkeypatch.setattr(retriever, "retrieve_fund_memory", fake_retrieve)
    result = fund_data.search_memory("why NVDA", k=3)
    assert result["status"] == "ok"
    assert result["results"][0]["id"] == "thesis:1"
