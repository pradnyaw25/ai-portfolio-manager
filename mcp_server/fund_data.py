"""Read-only query functions backing the fund MCP server.

Plain functions over the existing stores that return JSON-serializable dicts —
no `mcp` dependency, so they're unit-testable on their own. Every store is
injectable for testing; production defaults read the live `data/` files.
"""

from typing import Any

from src.storage.decision_store import DecisionStore
from src.storage.portfolio_store import PortfolioStore
from src.storage.run_history_store import RunHistoryStore
from src.storage.trade_store import TradeStore


def _in_range(day: str, since: str | None, until: str | None) -> bool:
    if since and day < since:
        return False
    if until and day > until:
        return False
    return True


def _decision_symbols(entry: dict) -> set[str]:
    symbols: set[str] = set()
    for key in ("executed_trades", "approved_trades", "rejected_trades", "rebalance_trades"):
        for trade in entry.get(key) or []:
            symbol = str(trade.get("symbol", "")).upper()
            if symbol:
                symbols.add(symbol)
    for trade in (entry.get("raw_decision") or {}).get("trades") or []:
        symbol = str(trade.get("symbol", "")).upper()
        if symbol:
            symbols.add(symbol)
    return symbols


def get_holdings(*, store: Any = None) -> dict:
    """Current portfolio: cash, positions, and per-position P&L."""
    snapshot = (store or PortfolioStore()).load()
    if snapshot is None:
        return {"status": "no_portfolio_state", "positions": []}
    return {
        "status": "ok",
        "date": snapshot.date.isoformat(),
        "cash": round(snapshot.cash, 2),
        "invested_value": round(snapshot.invested_value, 2),
        "total_value": round(snapshot.total_value, 2),
        "cash_pct": round(snapshot.cash_pct, 4),
        "positions": [
            {
                "symbol": p.symbol,
                "shares": p.shares,
                "avg_cost": round(p.avg_cost, 2),
                "current_price": round(p.current_price, 2),
                "market_value": round(p.market_value, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "return_pct": round(p.return_pct, 4),
            }
            for p in snapshot.positions
        ],
    }


def get_performance_history(*, limit: int = 20, store: Any = None) -> list[dict]:
    """Recent run summaries (newest first): value, cash, trades, status, cost."""
    rows = (store or RunHistoryStore()).load()
    rows = sorted(rows, key=lambda r: r.get("started_at", ""), reverse=True)[: max(1, limit)]
    return [
        {
            "run_id": r.get("run_id"),
            "started_at": r.get("started_at"),
            "completed_at": r.get("completed_at"),
            "status": r.get("status"),
            "portfolio_value": r.get("portfolio_value"),
            "cash_pct": r.get("cash_pct"),
            "trades_executed": r.get("trades_executed"),
            "llm_cost_usd": (r.get("llm") or {}).get("cost_usd"),
        }
        for r in rows
    ]


def list_trades(
    *,
    symbol: str | None = None,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    store: Any = None,
) -> list[dict]:
    """Executed trades, filterable by symbol/action/date range (newest first)."""
    symbol = symbol.upper() if symbol else None
    action = action.upper() if action else None
    rows = (store or TradeStore()).load_all()
    matched = [
        r
        for r in rows
        if (symbol is None or str(r.get("symbol", "")).upper() == symbol)
        and (action is None or str(r.get("action", "")).upper() == action)
        and _in_range(str(r.get("date", "")), since, until)
    ]
    matched.sort(key=lambda r: str(r.get("date", "")), reverse=True)
    return matched[: max(1, limit)]


def list_decisions(
    *,
    symbol: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
    store: Any = None,
) -> list[dict]:
    """Compact decision-journal summaries (newest first)."""
    symbol = symbol.upper() if symbol else None
    rows = (store or DecisionStore()).load_all()
    summaries = []
    for entry in rows:
        if not _in_range(str(entry.get("date", "")), since, until):
            continue
        if symbol and symbol not in _decision_symbols(entry):
            continue
        raw = entry.get("raw_decision") or {}
        summaries.append(
            {
                "run_id": entry.get("run_id"),
                "date": entry.get("date"),
                "outlook": raw.get("outlook"),
                "summary": raw.get("summary"),
                "executed": [
                    {"symbol": t.get("symbol"), "action": t.get("action"), "shares": t.get("shares")}
                    for t in entry.get("executed_trades") or []
                ],
                "has_debate": bool(raw.get("debate")),
            }
        )
    summaries.sort(key=lambda s: str(s.get("date", "")), reverse=True)
    return summaries[: max(1, limit)]


def _find_decision(rows: list[dict], run_id: str | None, day: str | None) -> dict | None:
    if run_id:
        for entry in rows:
            if entry.get("run_id") == run_id:
                return entry
        return None
    if day:
        matches = [e for e in rows if str(e.get("date", "")) == day]
        return matches[-1] if matches else None
    return rows[-1] if rows else None


def get_decision(*, run_id: str | None = None, date: str | None = None, store: Any = None) -> dict:
    """Full decision detail for a run (by run_id, by date, or the latest)."""
    entry = _find_decision((store or DecisionStore()).load_all(), run_id, date)
    if entry is None:
        return {"status": "not_found"}
    raw = entry.get("raw_decision") or {}
    return {
        "status": "ok",
        "run_id": entry.get("run_id"),
        "date": entry.get("date"),
        "outlook": raw.get("outlook"),
        "summary": raw.get("summary"),
        "market_summary": raw.get("market_summary"),
        "portfolio_assessment": raw.get("portfolio_assessment"),
        "risk_assessment": raw.get("risk_assessment"),
        "bear_case_response": raw.get("bear_case_response"),
        "cash_thesis": entry.get("cash_thesis"),
        "executed_trades": entry.get("executed_trades") or [],
        # HOLDs are no-ops, not trades; older entries wrongly logged low-confidence
        # HOLDs as "rejected", so exclude them from what the MCP reports as rejected.
        "rejected_trades": [
            t for t in (entry.get("rejected_trades") or [])
            if str(t.get("action", "")).upper() != "HOLD"
        ],
        "rebalance_trades": entry.get("rebalance_trades") or [],
        "risk_events": entry.get("risk_events") or [],
        "sources_used": raw.get("sources_used") or [],
        "grounding": entry.get("grounding"),
    }


def get_debate(*, run_id: str | None = None, date: str | None = None, store: Any = None) -> dict:
    """The bull/bear/risk debate transcript and PM bear-case response for a run."""
    entry = _find_decision((store or DecisionStore()).load_all(), run_id, date)
    if entry is None:
        return {"status": "not_found"}
    raw = entry.get("raw_decision") or {}
    debate = raw.get("debate")
    if not debate:
        return {"status": "no_debate", "run_id": entry.get("run_id"), "date": entry.get("date")}
    return {
        "status": "ok",
        "run_id": entry.get("run_id"),
        "date": entry.get("date"),
        "debate": debate,
        "bear_case_response": raw.get("bear_case_response"),
    }


def search_memory(query: str, *, k: int = 5) -> dict:
    """Semantic search over the fund's long-term memory (degrades if Qdrant is down)."""
    # Imported lazily so the rest of the module works without Qdrant/embeddings.
    from src.memory.retriever import retrieve_fund_memory

    result = retrieve_fund_memory(query=query, k=k)
    return {
        "status": result.status,
        "error": result.error,
        "results": [
            {
                "id": c.get("id"),
                "type": c.get("type"),
                "date": c.get("date"),
                "symbols": c.get("symbols"),
                "source_type": c.get("source_type"),
                "content": c.get("content"),
            }
            for c in result.chunks
        ],
    }
