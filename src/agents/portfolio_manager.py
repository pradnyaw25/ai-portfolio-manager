import json

from src.llm import complete_structured
from src.llm.schemas import DecisionResponse

PROMPT_VERSION = "portfolio_manager/v1"


class PortfolioManagerAgent:
    def decide(self, portfolio, research, benchmark, memory=None):
        memory_block = ""
        if memory:
            memory_block = (
                "\n\nTyped fund memory grouped by purpose:\n"
                f"{json.dumps(memory, indent=2)}\n"
            )

        context = f"""
You are an AI portfolio manager managing a simulated public $1M portfolio.

Your job:
1. Analyze the market context.
2. Decide whether to buy, sell, hold, or keep cash.
3. Avoid overtrading.
4. Explain cash if cash is high.
5. Return structured JSON only.
6. Use typed fund memory to maintain thesis continuity and avoid repeated mistakes.

Portfolio snapshot:
{portfolio}

Market context:
{research}

Benchmark:
{benchmark}
{memory_block}

Rules:
- Only trade symbols present in market_context.symbols.
- Prefer no trade over weak trades.
- Every trade must include confidence from 0.0 to 1.0.
- If cash_pct is above 0.25, include a cash_thesis.
- If memory influenced a conclusion, cite memory IDs in sources_used.
- Treat risk_lessons and recent_trades as higher-priority constraints than old theses.
- Do not output markdown.
- Do not invent prices or facts not present in the context.

Return ONLY valid JSON in this format:
{{
  "outlook": "BULLISH" | "NEUTRAL" | "BEARISH",
  "market_summary": "...",
  "portfolio_assessment": "...",
  "cash_thesis": "...",
  "risk_assessment": "...",
  "trades": [
    {{
      "symbol": "AAPL",
      "action": "BUY" | "SELL" | "HOLD",
      "shares": 10,
      "confidence": 0.74,
      "reason": "...",
      "risks": ["...", "..."],
      "sources_used": ["5d return", "30d return", "holding news"]
    }}
  ],
  "summary": "..."
}}
"""

        decision = complete_structured(
            [{"role": "user", "content": context}],
            DecisionResponse,
            tier="strong",
            prompt_version=PROMPT_VERSION,
        )

        # Return a plain dict — the risk manager, memory/citation layers, and
        # decision journal all consume the decision as a dict.
        return decision.model_dump()
