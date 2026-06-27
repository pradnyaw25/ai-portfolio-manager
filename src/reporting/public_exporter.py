import json
import shutil
from datetime import UTC, date, datetime
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
        run_id: str | None = None,
        run_status: dict | None = None,
    ) -> None:
        PUBLIC_DIR.mkdir(exist_ok=True)

        self._write_portfolio(snapshot, run_id=run_id)
        self._write_latest_trades(trades)
        self._write_latest_tweet(tweet, snapshot, run_id=run_id)
        self._write_latest_report(report_markdown)
        self._write_site_meta()
        if run_status is not None:
            self._write_run_status(run_status)
        self._write_prediction_dashboard()
        self._copy_history_files()

    def _write_portfolio(self, snapshot: PortfolioSnapshot, run_id: str | None = None) -> None:
        payload = {
            "run_id": run_id,
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
                "run_id": t.run_id,
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

    def _write_latest_tweet(
        self,
        tweet: str,
        snapshot: PortfolioSnapshot,
        run_id: str | None = None,
    ) -> None:
        payload = {
            "run_id": run_id,
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

    def _write_site_meta(self) -> None:
        payload = {
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

        (PUBLIC_DIR / "site_meta.json").write_text(json.dumps(payload, indent=2))

    def _write_run_status(self, run_status: dict) -> None:
        (PUBLIC_DIR / "run_status.json").write_text(json.dumps(run_status, indent=2))

    def _write_prediction_dashboard(self) -> None:
        predictions = self._load_predictions()
        resolved = [p for p in predictions if p.get("status") == "scored" and p.get("result")]
        open_predictions = [p for p in predictions if p.get("status") == "open"]
        wins = [p for p in resolved if p["result"].get("outperformed")]

        payload = {
            "metrics": {
                "total": len(predictions),
                "resolved": len(resolved),
                "open": len(open_predictions),
                "accuracy_pct": round((len(wins) / len(resolved)) * 100, 1) if resolved else None,
            },
            "best_predictions": self._rank_resolved_predictions(resolved, reverse=True)[:10],
            "worst_predictions": self._rank_resolved_predictions(resolved, reverse=False)[:10],
            "upcoming_predictions": sorted(
                [self._serialize_prediction(p) for p in open_predictions],
                key=lambda p: p.get("due_date") or "",
            )[:10],
        }

        (PUBLIC_DIR / "predictions.json").write_text(json.dumps(payload, indent=2))

    def _load_predictions(self) -> list[dict]:
        path = DATA_DIR / "predictions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _rank_resolved_predictions(self, predictions: list[dict], *, reverse: bool) -> list[dict]:
        ranked = [self._serialize_prediction(p) for p in predictions]
        return sorted(ranked, key=lambda p: p.get("alpha_pct", 0), reverse=reverse)

    def _serialize_prediction(self, prediction: dict) -> dict:
        result = prediction.get("result") or {}
        symbol_return = result.get("symbol_return")
        spy_return = result.get("spy_return")
        alpha_pct = None
        if symbol_return is not None and spy_return is not None:
            alpha_pct = round((symbol_return - spy_return) * 100, 2)

        return {
            "id": prediction.get("id"),
            "date": prediction.get("date"),
            "symbol": prediction.get("symbol"),
            "prediction": prediction.get("prediction"),
            "confidence": prediction.get("confidence"),
            "start_price": prediction.get("start_price"),
            "spy_start_price": prediction.get("spy_start_price"),
            "due_date": prediction.get("due_date"),
            "status": prediction.get("status"),
            "scored_date": result.get("scored_date"),
            "symbol_return": symbol_return,
            "spy_return": spy_return,
            "outperformed": result.get("outperformed"),
            "alpha_pct": alpha_pct,
        }

    def _copy_history_files(self) -> None:
        for filename in ["portfolio_history.csv", "trades.csv", "benchmark_history.csv", "decisions.jsonl", "predictions.jsonl"]:
            src = DATA_DIR / filename
            if src.exists():
                shutil.copy(src, PUBLIC_DIR / filename)
