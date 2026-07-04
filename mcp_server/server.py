#!/usr/bin/env python3
"""FastMCP server exposing the Glasshouse Fund (read-only).

Run directly (`python mcp_server/server.py`) or register with an MCP client
(Claude Desktop / Claude Code). All tools are read-only queries over the fund's
committed data — no tool can place a trade or mutate state.
"""

import sys
from pathlib import Path

# Launched as a bare script by MCP clients: put the repo root on the path so
# `mcp_server.*` and `src.*` import, then import the SDK (site-packages `mcp`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from mcp_server import fund_data

mcp = FastMCP("glasshouse-fund")


@mcp.tool()
def get_holdings() -> dict:
    """Current portfolio holdings: cash, each position's shares/cost/price, and
    per-position unrealized P&L and return."""
    return fund_data.get_holdings()


@mcp.tool()
def get_performance_history(limit: int = 20) -> list[dict]:
    """Recent daily runs (newest first): portfolio value, cash %, trades executed,
    status, and LLM cost per run."""
    return fund_data.get_performance_history(limit=limit)


@mcp.tool()
def list_trades(
    symbol: str | None = None,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Executed trades, newest first. Filter by symbol (e.g. "NVDA"), action
    ("BUY"/"SELL"), and/or an ISO date range (since/until, inclusive)."""
    return fund_data.list_trades(
        symbol=symbol, action=action, since=since, until=until, limit=limit
    )


@mcp.tool()
def list_decisions(
    symbol: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Compact decision-journal summaries (outlook, summary, executed trades),
    newest first. Filter by symbol and/or ISO date range."""
    return fund_data.list_decisions(symbol=symbol, since=since, until=until, limit=limit)


@mcp.tool()
def get_decision(run_id: str | None = None, date: str | None = None) -> dict:
    """Full reasoning for one decision — outlook, market/risk assessment, the PM's
    bear-case response, executed/rejected/rebalance trades, system risk events, and
    grounding. Look up by run_id, by ISO date, or omit both for the latest."""
    return fund_data.get_decision(run_id=run_id, date=date)


@mcp.tool()
def get_debate(run_id: str | None = None, date: str | None = None) -> dict:
    """The bull/bear/risk analyst debate transcript and the PM's bear-case response
    for a run. Look up by run_id, by ISO date, or omit both for the latest."""
    return fund_data.get_debate(run_id=run_id, date=date)


@mcp.tool()
def search_memory(query: str, k: int = 5) -> dict:
    """Semantic search over the fund's long-term memory (prior theses, risk lessons,
    trades, SEC/earnings context). Returns the top-k matches with source metadata."""
    return fund_data.search_memory(query, k=k)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
