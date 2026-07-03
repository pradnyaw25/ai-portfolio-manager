from datetime import date
from src.config import PROMPTS_DIR
from src.llm import complete_text
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "tweet_writer/v1"


class TweetGeneratorAgent:
    def __init__(self):
        self.system_prompt = (PROMPTS_DIR / "tweet_writer.txt").read_text()

    def generate(self, portfolio: PortfolioSnapshot, trades: list[Trade]) -> str:
        context = self._build_context(portfolio, trades)

        text = complete_text(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": context},
            ],
            tier="cheap",
            max_tokens=512,
            prompt_version=PROMPT_VERSION,
        )

        return self._clean_tweet(text)

    def _build_context(self, portfolio: PortfolioSnapshot, trades: list[Trade]) -> str:
        today = date.today().strftime("%b %d")

        if trades:
            trade_summary = ", ".join(
                f"{t.action.value} {t.symbol}" for t in trades
            )
        else:
            trade_summary = "No trades"

        return f"""Date: {today}
Portfolio Value: ${portfolio.total_value:,.0f}
Cash: ${portfolio.cash:,.0f} ({portfolio.cash_pct * 100:.1f}%)
Positions: {len(portfolio.positions)}
Trades: {trade_summary}
Tone: concise, factual, a little human. No disclaimer line. No cashtags.

Write the portfolio update now."""

    def _clean_tweet(self, text: str) -> str:
        lines = []
        for line in text.strip().splitlines():
            lower = line.lower()
            if "not investment advice" in lower:
                continue
            if "simulated portfolio" in lower:
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()[:280]
