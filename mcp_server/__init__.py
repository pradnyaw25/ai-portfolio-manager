"""Read-only MCP server exposing the Glasshouse Fund to any MCP client.

`fund_data` holds the plain, testable query functions over the existing stores;
`server` wires them into a FastMCP server. Kept out of `src/` and named
`mcp_server` (not `mcp`) so it never shadows the `mcp` SDK package.
"""
