import json

from src.llm import complete_structured
from src.llm.schemas import DecisionResponse

PROMPT_VERSION = "portfolio_manager/v1"


class PortfolioManagerAgent:
    def decide(self, portfolio, research, benchmark, memory=None, analysts=None):
        memory_block = ""
        if memory:
            memory_block = (
                "\n\nTyped fund memory grouped by purpose:\n"
                f"{json.dumps(memory, indent=2)}\n"
            )

        debate_block = ""
        bear_rule = ""
        bear_field = ""
        if analysts:
            debate_block = (
                "\n\nInvestment committee debate — weigh these three analyst views, "
                "then make the final call:\n"
                f"{json.dumps(analysts, default=str, indent=2)}\n"
            )
            bear_rule = (
                "\n- You MUST explicitly address the bear analyst's case in "
                "'bear_case_response': for each major bear point, say whether you "
                "accept or reject it and why. Do not ignore the bear case."
            )
            bear_field = '\n  "bear_case_response": "...",'

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
{memory_block}{debate_block}

Rules:
- Only trade symbols present in market_context.symbols.
- Prefer no trade over weak trades.
- Every trade must include confidence from 0.0 to 1.0.
- Populate 'market_calls' with ONE entry for EVERY symbol in market_context.symbols
  (holdings and watchlist alike), whether or not you trade it. A name you hold, or
  can't buy, or leave alone still has a view — record it. Each call states whether
  the name will OUTPERFORM or UNDERPERFORM SPY over the horizon, with a calibrated
  confidence from 0.0 to 1.0. Do NOT omit low-confidence names; a 0.55 is data.
  Report genuine confidence — do not round everything to 0.8.
- If cash_pct is above 0.25, include a cash_thesis.
- If memory influenced a conclusion, cite memory IDs in sources_used.
- Treat risk_lessons and recent_trades as higher-priority constraints than old theses.
- Do not output markdown.
- Do not invent prices or facts not present in the context.{bear_rule}

Return ONLY valid JSON in this format:
{{
  "outlook": "BULLISH" | "NEUTRAL" | "BEARISH",
  "market_summary": "...",
  "portfolio_assessment": "...",
  "cash_thesis": "...",
  "risk_assessment": "...",{bear_field}
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
  "market_calls": [
    {{
      "symbol": "AAPL",
      "direction": "OUTPERFORM" | "UNDERPERFORM",
      "confidence": 0.62,
      "thesis": "one line on why, vs SPY"
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
