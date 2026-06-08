import json
from openai import OpenAI
from src.config import PROMPTS_DIR
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TweetGeneratorAgent:
    def __init__(self):
        self.client = OpenAI()
        self.system_prompt = (PROMPTS_DIR / "tweet_writer.txt").read_text()

    def generate(self, portfolio: PortfolioSnapshot, trades: list[Trade]) -> str:
        context = self._build_context(portfolio, trades)

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=512,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": context},
            ],
        )

        return self._parse_response(response.choices[0].message.content)

    def _build_context(self, portfolio: PortfolioSnapshot, trades: list[Trade]) -> str:
        trade_lines = []
        for t in trades:
            trade_lines.append(f"  {t.action.value} {t.shares} {t.symbol} @ ${t.price:.2f}")
        trades_str = "\n".join(trade_lines) if trade_lines else "  No trades today"

        return f"""Portfolio Value: ${portfolio.total_value:,.2f}
Cash: ${portfolio.cash:,.2f}
Positions: {len(portfolio.positions)}

Today's Trades:
{trades_str}

Write an engaging tweet about today's portfolio activity."""

    def _parse_response(self, text: str) -> str:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
            return data.get("tweet", text)
        except (ValueError, json.JSONDecodeError):
            return text.strip()[:280]
