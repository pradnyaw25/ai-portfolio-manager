import json
import shutil
from datetime import date
from pathlib import Path

from src.config import DATA_DIR, REPORTS_DIR
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade


PUBLIC_DIR = Path("public")


class PublicExporter:
    def export(
        self,
        snapshot: PortfolioSnapshot,
        trades: list[Trade],
        tweet: str,
        report_markdown: str,
    ) -> None:
        PUBLIC_DIR.mkdir(exist_ok=True)

        self._write_portfolio(snapshot)
        self._write_latest_trades(trades)
        self._write_latest_tweet(tweet, snapshot)
        self._write_latest_report(report_markdown)
        self._copy_history_files()

    def _write_portfolio(self, snapshot: PortfolioSnapshot) -> None:
        payload = {
            "date": snapshot.date.isoformat(),
            "total_value": snapshot.total_value,
            "cash": snapshot.cash,
            "cash_pct": snapshot.cash_pct,
            "invested_value": snapshot.invested_value,
            "positions": [
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "return_pct": p.return_pct,
                }
                for p in snapshot.positions
            ],
        }

        (PUBLIC_DIR / "portfolio.json").write_text(
            json.dumps(payload, indent=2)
        )

    def _write_latest_trades(self, trades: list[Trade]) -> None:
        payload = [
            {
                "date": t.date.isoformat(),
                "symbol": t.symbol,
                "action": t.action.value,
                "shares": t.shares,
                "price": t.price,
                "total": t.total,
                "reasoning": t.reasoning,
            }
            for t in trades
        ]

        (PUBLIC_DIR / "latest_trades.json").write_text(
            json.dumps(payload, indent=2)
        )

    def _write_latest_tweet(self, tweet: str, snapshot: PortfolioSnapshot) -> None:
        payload = {
            "date": date.today().isoformat(),
            "text": tweet,
            "portfolio_value": snapshot.total_value,
            "posted": False,
        }

        (PUBLIC_DIR / "latest_tweet.json").write_text(
            json.dumps(payload, indent=2)
        )

    def _write_latest_report(self, report_markdown: str) -> None:
        (PUBLIC_DIR / "latest_report.md").write_text(report_markdown)

    def _copy_history_files(self) -> None:
        for filename in ["portfolio_history.csv", "trades.csv"]:
            src = DATA_DIR / filename
            if src.exists():
                shutil.copy(src, PUBLIC_DIR / filename)
