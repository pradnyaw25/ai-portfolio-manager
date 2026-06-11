import json
import uuid
from datetime import date, timedelta
from pathlib import Path

from src.config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"


class PredictionStore:
    def save(self, prediction: dict) -> None:
        if "id" not in prediction:
            prediction["id"] = str(uuid.uuid4())[:8]

        with open(PREDICTIONS_FILE, "a") as f:
            f.write(json.dumps(prediction) + "\n")

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

    def create_from_trade(self, trade, confidence: float, spy_price: float) -> dict:
        prediction = {
            "id": str(uuid.uuid4())[:8],
            "date": date.today().isoformat(),
            "symbol": trade.symbol,
            "prediction": f"{trade.symbol} will outperform SPY over 30 days",
            "confidence": confidence,
            "start_price": trade.price,
            "spy_start_price": spy_price,
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "status": "open",
            "result": None,
        }
        self.save(prediction)
        return prediction
