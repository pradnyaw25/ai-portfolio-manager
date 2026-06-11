import json
from openai import OpenAI

client = OpenAI()


class PortfolioManagerAgent:
    def decide(self, portfolio, research, benchmark):
        context = f"""
You are an AI portfolio manager managing a simulated public $1M portfolio.

Your job:
1. Analyze the market context.
2. Decide whether to buy, sell, hold, or keep cash.
3. Avoid overtrading.
4. Explain cash if cash is high.
5. Return structured JSON only.

Portfolio snapshot:
{portfolio}

Market context:
{research}

Benchmark:
{benchmark}

Rules:
- Only trade symbols present in market_context.symbols.
- Prefer no trade over weak trades.
- Every trade must include confidence from 0.0 to 1.0.
- If cash_pct is above 0.25, include a cash_thesis.
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

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": context}
            ],
            response_format={"type": "json_object"},
        )

        return json.loads(response.choices[0].message.content)
