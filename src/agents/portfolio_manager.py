import json
from openai import OpenAI

client = OpenAI()


class PortfolioManagerAgent:
    def decide(self, portfolio, research, benchmark):
        context = f"""
You are an AI portfolio manager.

Current portfolio:
{portfolio}

Research:
{research}

Benchmark:
{benchmark}

Return ONLY valid JSON in this format:
{{
  "trades": [
    {{
      "symbol": "AAPL",
      "action": "BUY",
      "shares": 10,
      "reason": "..."
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
