from datetime import date

from src.storage.prediction_store import PredictionStore, shadow_stores
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PredictionScorer:
    def __init__(self):
        self.store = PredictionStore()

    def score_due_predictions(self, market_data) -> list[dict]:
        """Score the fund's own due predictions and return them. Shadow stores are
        scored too (same prices, same day) but their rows are not returned — nothing
        downstream (receipts tweet, reflection) should ever see a shadow call."""
        try:
            spy_price = market_data.get_price("SPY")
        except Exception:
            logger.warning("Could not fetch SPY price — skipping prediction scoring")
            return []

        scored = self._score_store(self.store, market_data, spy_price)
        for store in shadow_stores():
            try:
                self._score_store(store, market_data, spy_price)
            except Exception as exc:  # a shadow file must never fail the fund's scoring
                logger.warning("Shadow scoring skipped for %s: %s", store.path.name, exc)
        return scored

    def _score_store(self, store: PredictionStore, market_data, spy_price: float) -> list[dict]:
        all_predictions = store.load_all()
        today = date.today().isoformat()
        scored = []

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
            # A prediction is CORRECT when the realized direction matches the call.
            # Legacy rows have no `direction` and were all "outperform" bets.
            predicted_outperform = str(p.get("direction", "OUTPERFORM")).upper() == "OUTPERFORM"
            correct = outperformed == predicted_outperform

            p["status"] = "scored"
            p["result"] = {
                "end_price": current_price,
                "spy_end_price": spy_price,
                "symbol_return": round(symbol_return, 4),
                "spy_return": round(spy_return, 4),
                "alpha": round(symbol_return - spy_return, 4),
                "outperformed": outperformed,
                "correct": correct,
                "scored_date": today,
            }

            outcome = "WIN" if correct else "LOSS"
            logger.info(
                "Prediction %s: %s %s (%.2f%% vs SPY %.2f%%)",
                outcome, symbol, p["prediction"],
                symbol_return * 100, spy_return * 100,
            )

            scored.append(p)
            updated = True

        if updated:
            store.save_all(all_predictions)

        return scored
