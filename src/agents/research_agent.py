"""Tool-calling research agent (augments the deterministic market context).

Given the base research context, this agent uses typed tools to do targeted
follow-up (deep-dive a mover, pull a catalyst's news, check memory for a name)
and writes a short brief. It runs on the cheap tier. The base context from
``MarketContextBuilder`` is unchanged; this only adds a brief + the tool-call
trace, which flow into the decision journal and dashboard.
"""

import json

from pydantic import BaseModel, Field

from src.llm import complete_with_tools
from src.llm.tools import Tool, ToolRegistry
from src.memory.retriever import retrieve_grouped_fund_memory
from src.utils.logger import get_logger

logger = get_logger(__name__)

RESEARCH_PROMPT_VERSION = "research_analyst/v1"


# -- tool input schemas ------------------------------------------------------


class SymbolInput(BaseModel):
    symbol: str


class HistoryInput(BaseModel):
    symbol: str
    days: int = 30


class NewsInput(BaseModel):
    query: str
    limit: int = 5


class MemoryInput(BaseModel):
    query: str
    symbols: list[str] = Field(default_factory=list)


class EmptyInput(BaseModel):
    pass


def build_research_registry(market_data, news_client, snapshot) -> ToolRegistry:
    """Construct the tool registry bound to this run's clients + snapshot."""

    def get_price(args: SymbolInput) -> dict:
        return {"symbol": args.symbol.upper(), "price": round(market_data.get_price(args.symbol), 2)}

    def get_history(args: HistoryInput) -> dict:
        hist = market_data.get_history(args.symbol, days=args.days)
        if hist.empty or len(hist) < 2:
            return {"symbol": args.symbol.upper(), "error": "no history"}
        start = float(hist["Close"].iloc[0])
        end = float(hist["Close"].iloc[-1])
        return {
            "symbol": args.symbol.upper(),
            "days": args.days,
            "start_price": round(start, 2),
            "end_price": round(end, 2),
            "return_pct": round((end / start - 1) * 100, 2) if start else None,
        }

    def search_news(args: NewsInput) -> dict:
        articles = news_client.get_stock_news(args.query, limit=args.limit)
        return {
            "query": args.query,
            "articles": [
                {"title": a.get("title", ""), "source": a.get("source", ""), "published": a.get("published", "")}
                for a in articles
            ],
        }

    def retrieve_memory(args: MemoryInput) -> dict:
        result = retrieve_grouped_fund_memory(query=args.query, symbols=args.symbols or None, k_per_group=3)
        return {
            "status": result.status,
            "memories": [
                {"id": c.get("id"), "type": c.get("type"), "content": (c.get("content") or "")[:280]}
                for c in result.chunks[:6]
            ],
        }

    def get_portfolio(_args: EmptyInput) -> dict:
        return {
            "total_value": snapshot.total_value,
            "cash": snapshot.cash,
            "cash_pct": round(snapshot.cash_pct, 4),
            "positions": [
                {"symbol": p.symbol, "shares": p.shares, "return_pct": round(p.return_pct, 4)}
                for p in snapshot.positions
            ],
        }

    return ToolRegistry([
        Tool("get_price", "Latest price for a symbol.", SymbolInput, get_price),
        Tool("get_history", "Price history summary (return over N days) for a symbol.", HistoryInput, get_history),
        Tool("search_news", "Recent news headlines for a query or symbol.", NewsInput, search_news),
        Tool("retrieve_memory", "Retrieve prior fund memory (theses, lessons, trades) for a query.", MemoryInput, retrieve_memory),
        Tool("get_portfolio", "Current portfolio holdings and cash.", EmptyInput, get_portfolio),
    ])


class ResearchAnalyst:
    def investigate(self, base_research, registry, *, complete_fn=None) -> dict:
        complete_fn = complete_fn or complete_with_tools
        prompt = (
            "You are the research analyst on an investment committee. The deterministic "
            "base context is below. Use the available tools to investigate the few most "
            "decision-relevant open questions (a notable mover, a catalyst, a concentrated "
            "position, relevant prior memory). Make a handful of targeted tool calls, then "
            "write a concise research brief (5-8 sentences) of what matters for today's "
            "decision. Only state facts returned by the tools or present in the base "
            "context; do not fabricate numbers.\n\n"
            f"Base context:\n{json.dumps(base_research, default=str)[:3000]}"
        )
        result = complete_fn(
            [{"role": "user", "content": prompt}],
            registry,
            tier="cheap",
            prompt_version=RESEARCH_PROMPT_VERSION,
        )
        logger.info("Research agent made %d tool call(s)", len(result.tool_calls))
        return {"brief": result.content, "tool_calls": result.tool_calls}
