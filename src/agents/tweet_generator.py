from datetime import date

from src.config import PROMPTS_DIR
from src.llm import complete_text
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "tweet_writer/v2"


class TweetGeneratorAgent:
    def __init__(self):
        self.system_prompt = (PROMPTS_DIR / "tweet_writer.txt").read_text()

    def generate(
        self,
        portfolio: PortfolioSnapshot,
        trades: list[Trade],
        decisions: dict | None = None,
    ) -> str:
        context = self._build_context(portfolio, trades, decisions or {})

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

    def _build_context(
        self, portfolio: PortfolioSnapshot, trades: list[Trade], decisions: dict
    ) -> str:
        today = date.today().strftime("%b %d")

        # Trades WITH the fund's reasoning — the thesis is the interesting part, not the
        # bare "BUY AAPL". Reasons come from the PM's raw decision, keyed by symbol+action.
        reason_by = {
            (str(t.get("symbol", "")).upper(), str(t.get("action", "")).upper()): (t.get("reason") or "")
            for t in decisions.get("trades", [])
        }
        if trades:
            trade_lines = []
            for t in trades:
                reason = reason_by.get((t.symbol.upper(), t.action.value.upper()), "")
                line = f"- {t.action.value} {t.symbol}"
                if reason:
                    line += f" — {reason[:160]}"
                trade_lines.append(line)
            trades_block = "Today's trades and the fund's reasoning:\n" + "\n".join(trade_lines)
        else:
            trades_block = "Today's trades: none — the fund held."

        # The sharpest scored calls (beat/lag the S&P). These carry a real view and give
        # the tweet something to say on quiet days. Show the top few by conviction.
        calls = sorted(
            decisions.get("market_calls", []),
            key=lambda c: c.get("confidence") or 0,
            reverse=True,
        )[:3]
        if calls:
            call_lines = []
            for c in calls:
                verb = "lag" if str(c.get("direction") or "").upper() == "UNDERPERFORM" else "beat"
                conf = (c.get("confidence") or 0) * 100
                thesis = str(c.get("thesis") or "")[:140]
                call_lines.append(
                    f"- {c.get('symbol')}: {verb} the S&P 500 over ~1 month, {conf:.0f}% conviction"
                    + (f" — {thesis}" if thesis else "")
                )
            calls_block = (
                "The fund's sharpest directional calls (its scored predictions vs the S&P 500):\n"
                + "\n".join(call_lines)
            )
        else:
            calls_block = ""

        outlook = str(decisions.get("outlook") or "").strip()
        outlook_line = f"Market outlook: {outlook}\n" if outlook else ""

        return f"""Date: {today}
{outlook_line}Portfolio value: ${portfolio.total_value:,.0f} (background only — do not lead with this)

{trades_block}

{calls_block}

Write the one tweet now — lead with the most interesting thing and say why."""

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
