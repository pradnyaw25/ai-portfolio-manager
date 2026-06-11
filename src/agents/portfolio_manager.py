import json
from openai import OpenAI

from src.config import TARGET_CASH_PCT

client = OpenAI()


class PortfolioManagerAgent:
    def decide(self, portfolio, research, benchmark):
        cash_pct = portfolio.cash_pct * 100
        target_pct = TARGET_CASH_PCT * 100

        context = f"""
You are an AI portfolio manager. Your job is to actively manage a portfolio, not sit in cash.

Current portfolio:
{portfolio}

Cash allocation: {cash_pct:.1f}% (target maximum: {target_pct:.0f}%)

Research:
{research}

Benchmark:
{benchmark}

CASH ALLOCATION RULES:
- Your target maximum cash is {target_pct:.0f}% of portfolio value.
- If cash exceeds {target_pct:.0f}%, you MUST either:
  1. Propose BUY trades to deploy excess cash into your highest-conviction ideas, OR
  2. Include a "cash_thesis" field with a detailed explanation of why holding elevated cash
     is the correct decision right now (e.g., imminent recession risk, extreme valuations,
     pending catalyst). "Being cautious" alone is NOT sufficient.
- Spread deployments across multiple positions to maintain diversification.

Return ONLY valid JSON in this format:
{{
  "trades": [
    {{
      "symbol": "AAPL",
      "action": "BUY",
      "shares": 10,
      "confidence": 0.75,
      "reason": "..."
    }}
  ],
  "summary": "...",
  "outlook": "BULLISH",
  "risk_assessment": "...",
  "cash_thesis": null
}}

"cash_thesis" must be null if you are deploying cash below {target_pct:.0f}%, or a detailed
string explaining why holding cash above {target_pct:.0f}% is justified.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": context}
            ],
            response_format={"type": "json_object"},
        )

        return json.loads(response.choices[0].message.content)
