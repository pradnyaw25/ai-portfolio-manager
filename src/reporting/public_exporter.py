import json
import shutil
import csv
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
            self._write_memory_health(run_status)
        self._write_social_audit()
        self._write_prediction_dashboard()
        self._copy_history_files()

    def write_run_status(self, run_status: dict) -> None:
        PUBLIC_DIR.mkdir(exist_ok=True)
        self._write_run_status(run_status)
        self._write_memory_health(run_status)

    def update_latest_tweet_status(self, publish_result: dict) -> None:
        PUBLIC_DIR.mkdir(exist_ok=True)
        path = PUBLIC_DIR / "latest_tweet.json"
        payload = {}
        if path.exists():
            payload = json.loads(path.read_text())
        payload.update(
            {
                "posted": publish_result.get("posted", False),
                "publish_status": publish_result.get("status"),
                "tweet_id": publish_result.get("tweet_id"),
                "tweet_url": publish_result.get("tweet_url")
                or _tweet_url(publish_result.get("tweet_id")),
                "publish_error": publish_result.get("error"),
                "publish_error_code": publish_result.get("error_code"),
                "publish_http_status": publish_result.get("http_status"),
                "published_at": publish_result.get("created_at")
                if publish_result.get("posted")
                else None,
            }
        )
        path.write_text(json.dumps(payload, indent=2))
        self._write_social_audit()

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

    def _write_social_audit(self) -> None:
        posts = self._load_jsonl(DATA_DIR / "social_posts.jsonl")
        enriched_posts = [self._serialize_social_post(post) for post in posts]
        latest = enriched_posts[-1] if enriched_posts else None
        payload = {
            "updated_at": _utc_now(),
            "metrics": {
                "total": len(enriched_posts),
                "posted": sum(1 for post in enriched_posts if post.get("posted")),
                "errors": sum(1 for post in enriched_posts if post.get("status") == "error"),
                "dry_runs": sum(1 for post in enriched_posts if post.get("dry_run")),
                "latest_status": latest.get("status") if latest else None,
                "latest_run_id": latest.get("run_id") if latest else None,
            },
            "posts": list(reversed(enriched_posts[-25:])),
        }
        (PUBLIC_DIR / "social_posts.json").write_text(json.dumps(payload, indent=2))

        source = DATA_DIR / "social_posts.jsonl"
        if source.exists():
            shutil.copy(source, PUBLIC_DIR / "social_posts.jsonl")

    def _serialize_social_post(self, post: dict) -> dict:
        tweet_id = post.get("tweet_id")
        return {
            "run_id": post.get("run_id"),
            "created_at": post.get("created_at"),
            "status": post.get("status"),
            "posted": post.get("posted", False),
            "dry_run": post.get("dry_run", False),
            "tweet_id": tweet_id,
            "tweet_url": post.get("tweet_url")
            or (f"https://x.com/i/web/status/{tweet_id}" if tweet_id else None),
            "error": post.get("error"),
            "error_code": post.get("error_code"),
            "http_status": post.get("http_status"),
            "text": post.get("text", ""),
        }

    def _write_memory_health(self, run_status: dict | None = None) -> None:
        status = run_status or self._load_json(PUBLIC_DIR / "run_status.json") or {}
        payload = {
            "updated_at": _utc_now(),
            "run_id": status.get("run_id"),
            "retrieval": {
                "status": status.get("memory_status"),
                "error": status.get("memory_error"),
                "chunks": status.get("memory_chunks", 0),
            },
            "ingestion": status.get("memory_ingestion")
            or {
                "status": "not_recorded",
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [],
                "total_processed": 0,
            },
            "sources": {
                "reports": self._summarize_reports(),
                "decisions": self._summarize_jsonl(DATA_DIR / "decisions.jsonl"),
                "trades": self._summarize_csv(DATA_DIR / "trades.csv"),
                "sec_filings": self._load_json(DATA_DIR / "memory_sec_filings.json"),
                "eval": self._load_json(DATA_DIR / "memory_eval_latest.json"),
            },
            "warnings": status.get("warnings", []),
        }
        (PUBLIC_DIR / "memory_health.json").write_text(json.dumps(payload, indent=2))

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

    def _load_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def _summarize_reports(self) -> dict:
        reports = sorted(REPORTS_DIR.glob("report_*.md"))
        latest = reports[-1] if reports else None
        return {
            "count": len(reports),
            "latest": latest.name if latest else None,
            "latest_updated_at": _file_mtime(latest) if latest else None,
        }

    def _summarize_jsonl(self, path: Path) -> dict:
        rows = self._load_jsonl(path)
        latest = rows[-1] if rows else {}
        return {
            "count": len(rows),
            "latest_run_id": latest.get("run_id"),
            "latest_date": latest.get("date") or latest.get("created_at"),
        }

    def _summarize_csv(self, path: Path) -> dict:
        if not path.exists():
            return {"count": 0, "latest_date": None, "latest_run_id": None}
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        latest = rows[-1] if rows else {}
        return {
            "count": len(rows),
            "latest_date": latest.get("date"),
            "latest_run_id": latest.get("run_id"),
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _file_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")


def _tweet_url(tweet_id: str | None) -> str | None:
    if not tweet_id:
        return None
    return f"https://x.com/i/web/status/{tweet_id}"
