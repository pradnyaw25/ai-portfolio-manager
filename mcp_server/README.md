# Fund MCP Server

A read-only [MCP](https://modelcontextprotocol.io) server that exposes the AI
Portfolio Manager fund to any MCP client (Claude Desktop, Claude Code, etc.), so
you can ask questions like *"why did the fund sell NVDA in June?"* against the real
committed data.

## Tools (all read-only)

| Tool | What it answers |
|------|-----------------|
| `get_holdings` | Current positions, cash, and per-position P&L |
| `get_performance_history` | Recent runs: portfolio value, cash %, trades, LLM cost |
| `list_trades` | Executed trades, filterable by symbol / action / date range |
| `list_decisions` | Compact decision-journal summaries |
| `get_decision` | Full reasoning for one decision (outlook, assessments, trades, risk events, grounding) |
| `get_debate` | The bull/bear/risk debate transcript for a run |
| `search_memory` | Semantic search over the fund's long-term memory |

No tool can place a trade or mutate state.

## Run

```bash
make mcp            # or: python mcp_server/server.py
```

The server speaks MCP over stdio.

## Register with Claude Desktop / Claude Code

Add to your MCP client config (e.g. `claude_desktop_config.json`), pointing at this
repo's Python and absolute paths:

```json
{
  "mcpServers": {
    "ai-portfolio-manager": {
      "command": "/absolute/path/to/repo/.venv/bin/python",
      "args": ["/absolute/path/to/repo/mcp_server/server.py"]
    }
  }
}
```

`search_memory` needs `OPENAI_API_KEY` and a reachable `QDRANT_URL` (set them in the
environment or your MCP client's `env`); it degrades gracefully to
`status: "unavailable"` if memory is offline. All other tools read local files only.
