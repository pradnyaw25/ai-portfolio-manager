from datetime import date
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

        return response.choices[0].message.content.strip()[:280]

    def _build_context(self, portfolio: PortfolioSnapshot, trades: list[Trade]) -> str:
        today = date.today().strftime("%b %d")

        if trades:
            trade_summary = ", ".join(
                f"{t.action.value} ${t.symbol}" for t in trades
            )
        else:
            trade_summary = "No trades"

        return f"""Date: {today}
Portfolio Value: ${portfolio.total_value:,.0f}
Cash: ${portfolio.cash:,.0f} ({portfolio.cash_pct * 100:.1f}%)
Positions: {len(portfolio.positions)}
Trades: {trade_summary}

Write the portfolio update now."""
