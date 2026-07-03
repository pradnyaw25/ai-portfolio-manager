import json
import uuid
from datetime import date, timedelta
from pathlib import Path

from src.config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"

# Namespace for deterministic prediction IDs. Keying the id on (run_id, symbol)
# means re-running a run recreates the same id, so upsert leaves an identical row.
_PREDICTION_NAMESPACE = uuid.UUID("6f2a4e1c-0b7d-4f8a-9c3e-2a1b5d6e7f80")


def _prediction_id(run_id: str | None, symbol: str | None) -> str:
    if run_id and symbol:
        return str(uuid.uuid5(_PREDICTION_NAMESPACE, f"{run_id}:{symbol}"))[:8]
    return str(uuid.uuid4())[:8]


class PredictionStore:
    def save(self, prediction: dict) -> None:
        if "id" not in prediction:
            prediction["id"] = _prediction_id(
                prediction.get("run_id"), prediction.get("symbol")
            )

        run_id, symbol = prediction.get("run_id"), prediction.get("symbol")
        entries = self.load_all()
        if run_id is not None and symbol is not None:
            # One prediction per (run_id, symbol): re-running a run replaces its
            # prediction rather than appending a duplicate.
            entries = [
                p for p in entries
                if not (p.get("run_id") == run_id and p.get("symbol") == symbol)
            ]
        entries.append(prediction)
        self.save_all(entries)

        logger.info("Saved prediction: %s %s", prediction["symbol"], prediction["prediction"])

    def load_all(self) -> list[dict]:
        if not PREDICTIONS_FILE.exists():
            return []
        entries = []
        for line in PREDICTIONS_FILE.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def load_open(self) -> list[dict]:
        return [p for p in self.load_all() if p.get("status") == "open"]

    def save_all(self, predictions: list[dict]) -> None:
        with open(PREDICTIONS_FILE, "w") as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")

    HORIZON_DAYS = 30

    def create_from_trade(self, trade, confidence: float, spy_price: float) -> dict:
        horizon = self.HORIZON_DAYS
        run_id = getattr(trade, "run_id", None)
        prediction = {
            "id": _prediction_id(run_id, trade.symbol),
            "run_id": run_id,
            "date": date.today().isoformat(),
            "symbol": trade.symbol,
            "prediction": f"{trade.symbol} will outperform SPY over {horizon} days",
            "thesis": getattr(trade, "reasoning", "") or "",
            "horizon_days": horizon,
            "confidence": confidence,
            "start_price": trade.price,
            "spy_start_price": spy_price,
            "due_date": (date.today() + timedelta(days=horizon)).isoformat(),
            "status": "open",
            "result": None,
        }
        self.save(prediction)
        return prediction
