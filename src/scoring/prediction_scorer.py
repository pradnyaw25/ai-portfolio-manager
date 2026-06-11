from datetime import date

from src.storage.prediction_store import PredictionStore
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PredictionScorer:
    def __init__(self):
        self.store = PredictionStore()

    def score_due_predictions(self, market_data) -> list[dict]:
        all_predictions = self.store.load_all()
        today = date.today().isoformat()
        scored = []

        try:
            spy_price = market_data.get_price("SPY")
        except Exception:
            logger.warning("Could not fetch SPY price — skipping prediction scoring")
            return []

        updated = False
        for p in all_predictions:
            if p.get("status") != "open":
                continue
            if p.get("due_date", "") > today:
                continue

            symbol = p["symbol"]
            try:
                current_price = market_data.get_price(symbol)
            except Exception:
                logger.warning("Could not fetch price for %s — skipping", symbol)
                continue

            symbol_return = (current_price / p["start_price"]) - 1
            spy_return = (spy_price / p["spy_start_price"]) - 1
            outperformed = symbol_return > spy_return

            p["status"] = "scored"
            p["result"] = {
                "end_price": current_price,
                "spy_end_price": spy_price,
                "symbol_return": round(symbol_return, 4),
                "spy_return": round(spy_return, 4),
                "outperformed": outperformed,
                "scored_date": today,
            }

            outcome = "WIN" if outperformed else "LOSS"
            logger.info(
                "Prediction %s: %s %s (%.2f%% vs SPY %.2f%%)",
                outcome, symbol, p["prediction"],
                symbol_return * 100, spy_return * 100,
            )

            scored.append(p)
            updated = True

        if updated:
            self.store.save_all(all_predictions)

        return scored
