import re
from datetime import UTC, date, datetime

from src.config import BENCHMARK_SYMBOLS, PROMPTS_DIR, WATCHLIST
from src.llm import complete_text
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "tweet_writer/v2"

# Indices are references ("beat the S&P 500"), not the tweet's subject, so they never
# earn a cashtag and don't count toward the "only one symbol" test.
_BENCHMARKS = {s.upper() for s in BENCHMARK_SYMBOLS}

_SITE = "glasshousefund.com"
_TWEET_LIMIT = 280
# A plain equity ticker, eligible for a symbol-hub link.
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


class TweetGeneratorAgent:
    def __init__(self):
        self.system_prompt = (PROMPTS_DIR / "tweet_writer.txt").read_text()

    def generate(
        self,
        portfolio: PortfolioSnapshot,
        trades: list[Trade],
        decisions: dict | None = None,
        research: dict | None = None,
    ) -> str:
        context = self._build_context(
            portfolio, trades, decisions or {}, research or {}, self._cooldown_symbols()
        )

        text = complete_text(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": context},
            ],
            tier="cheap",
            max_tokens=512,
            prompt_version=PROMPT_VERSION,
        )

        cleaned = self._clean_tweet(text)
        known = self._known_symbols(portfolio, trades, decisions or {})
        # Compute mentions on the pre-cashtag text (a $ prefix would hide the ticker
        # from the matcher); the same set drives both the cashtag and the link target.
        mentioned = self._mentioned_symbols(cleaned, known)
        tagged = self._apply_cashtag(cleaned, known)
        return self._append_link(tagged, mentioned)

    def _cooldown_symbols(self) -> set[str]:
        """Symbols the fund has tweeted about within the cooldown window. Best-effort:
        if the post log can't be read, no name is suppressed and tweeting proceeds."""
        try:
            from src.social.cooldown import load_recent_posts, recent_tweet_symbols

            return recent_tweet_symbols(load_recent_posts(), now=datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 — variety is a nicety, never fail a tweet
            logger.warning("Tweet cooldown lookup skipped: %s", exc)
            return set()

    def _build_context(
        self,
        portfolio: PortfolioSnapshot,
        trades: list[Trade],
        decisions: dict,
        research: dict,
        cooldown_symbols: set[str] | None = None,
    ) -> str:
        cooldown_symbols = cooldown_symbols or set()
        today = date.today().strftime("%b %d")

        # Headlines per symbol, so a trade can be tied to its actual news catalyst.
        news_by = {
            str(sym).upper(): [a.get("title", "").strip() for a in (arts or []) if a.get("title")]
            for sym, arts in (research.get("symbol_news") or {}).items()
        }

        # Trades WITH the fund's reasoning AND the news behind them — the thesis and its
        # catalyst are the interesting part, not the bare "BUY AAPL".
        reason_by = {
            (str(t.get("symbol", "")).upper(), str(t.get("action", "")).upper()): (t.get("reason") or "")
            for t in decisions.get("trades", [])
        }
        if trades:
            trade_lines = []
            for t in trades:
                sym = t.symbol.upper()
                reason = reason_by.get((sym, t.action.value.upper()), "")
                line = f"- {t.action.value} {t.symbol}"
                if reason:
                    line += f" — {reason[:160]}"
                headlines = news_by.get(sym, [])[:2]
                for h in headlines:
                    line += f'\n    news: "{h[:120]}"'
                trade_lines.append(line)
            trades_block = "Today's trades, the fund's reasoning, and the news behind them:\n" + "\n".join(trade_lines)
        else:
            trades_block = "Today's trades: none — the fund held."

        # The sharpest scored calls (beat/lag the S&P). These carry a real view and give
        # the tweet something to say on quiet days. Rank fresh names (not tweeted inside
        # the cooldown) ahead of recently-featured ones, then by conviction — so a quiet
        # day doesn't lead with the same name three days running. Confidence still breaks
        # ties, and if every call is on cooldown they simply sort by conviction as before.
        def _call_rank(call: dict) -> tuple[bool, float]:
            symbol = str(call.get("symbol", "")).upper()
            confidence = call.get("confidence") or 0
            return (symbol in cooldown_symbols, -confidence)

        calls = sorted(decisions.get("market_calls", []), key=_call_rank)[:3]
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

        # A few top market headlines — useful on quiet days, and only when relevant.
        market_headlines = [
            n.get("title", "").strip() for n in (research.get("market_news") or []) if n.get("title")
        ][:3]
        market_block = (
            "Today's notable market headlines:\n"
            + "\n".join(f'- "{h[:120]}"' for h in market_headlines)
            if market_headlines
            else ""
        )

        blocks = "\n\n".join(b for b in (trades_block, calls_block, market_block) if b)
        return f"""Date: {today}
{outlook_line}Portfolio value: ${portfolio.total_value:,.0f} (background only — do not lead with this)

{blocks}

Write the one tweet now — lead with the most interesting thing and say why. If a specific headline is the real catalyst behind a trade or the market view, work it in; don't force it otherwise."""

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

    def _known_symbols(
        self, portfolio: PortfolioSnapshot, trades: list[Trade], decisions: dict
    ) -> set[str]:
        """The fund's ticker vocabulary for this tweet — everything it could plausibly
        name — used to detect symbol mentions reliably (matching bare uppercase words
        against a known set, not guessing which words are tickers). Benchmarks excluded."""
        syms = set(WATCHLIST)
        syms |= {t.symbol.upper() for t in trades}
        syms |= {p.symbol.upper() for p in portfolio.positions}
        for c in decisions.get("market_calls", []):
            syms.add(str(c.get("symbol", "")).upper())
        for t in decisions.get("trades", []):
            syms.add(str(t.get("symbol", "")).upper())
        return {s for s in syms if s} - _BENCHMARKS

    def _mentioned_symbols(self, text: str, known_symbols: set[str]) -> list[str]:
        """Which known tickers appear as bare uppercase words in ``text``."""
        return [
            sym
            for sym in known_symbols
            if re.search(rf"(?<![\w$]){re.escape(sym)}(?![\w])", text)
        ]

    def _apply_cashtag(self, text: str, known_symbols: set[str]) -> str:
        """If exactly one known symbol is named, turn its first mention into a cashtag
        ($AAPL). A lone cashtag surfaces a single-name tweet in that ticker's feed;
        several cashtags read as spam (and X throttles them), so multi-name tweets stay
        plain. The model is told to write plain tickers — this owns the cashtag rule so
        it stays deterministic rather than trusting the model to count."""
        mentioned = self._mentioned_symbols(text, known_symbols)
        if len(mentioned) != 1:
            return text
        sym = mentioned[0]
        if re.search(rf"\${re.escape(sym)}(?![\w])", text):
            return text  # already a cashtag
        return re.sub(rf"(?<![\w$]){re.escape(sym)}(?![\w])", f"${sym}", text, count=1)

    def _link_for(self, mentioned: list[str]) -> str:
        """The 'read more' target. A single-name tweet points at that ticker's hub —
        the stock's full decision history, and a page that already exists from prior
        runs (no deploy-lag 404). Otherwise the dashboard."""
        if len(mentioned) == 1 and _TICKER_RE.match(mentioned[0]):
            return f"{_SITE}/symbols/{mentioned[0]}.html"
        return f"{_SITE}/dashboard.html"

    def _append_link(self, text: str, mentioned: list[str]) -> str:
        """Append the link on its own line, trimming the body (never the URL) to stay
        within the tweet limit."""
        url = self._link_for(mentioned)
        if url in text:
            return text[:_TWEET_LIMIT]
        room = _TWEET_LIMIT - len(url) - 1  # newline
        return f"{text[:room].rstrip()}\n{url}"
