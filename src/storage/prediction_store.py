import json
import uuid
from datetime import date, timedelta

from src.config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"

# Namespace for deterministic prediction IDs. Keying the id on (run_id, symbol)
# means re-running a run recreates the same id, so upsert leaves an identical row.
_PREDICTION_NAMESPACE = uuid.UUID("6f2a4e1c-0b7d-4f8a-9c3e-2a1b5d6e7f80")


def _prediction_id(
    run_id: str | None, symbol: str | None, horizon: int | None = None
) -> str:
    if run_id and symbol:
        # Horizon is part of the key so a single run can hold independent 5d and
        # 30d predictions for the same name without their ids colliding.
        key = f"{run_id}:{symbol}:{horizon}" if horizon is not None else f"{run_id}:{symbol}"
        return str(uuid.uuid5(_PREDICTION_NAMESPACE, key))[:8]
    return str(uuid.uuid4())[:8]


class PredictionStore:
    def save(self, prediction: dict) -> None:
        if "id" not in prediction:
            prediction["id"] = _prediction_id(
                prediction.get("run_id"), prediction.get("symbol")
            )

        run_id, symbol = prediction.get("run_id"), prediction.get("symbol")
        horizon = prediction.get("horizon_days")
        entries = self.load_all()
        if run_id is not None and symbol is not None:
            # One prediction per (run_id, symbol, horizon): re-running a run
            # replaces its prediction rather than appending a duplicate. Horizon is
            # part of the key so a run's 5d row does not clobber its 30d row.
            entries = [
                p for p in entries
                if not (
                    p.get("run_id") == run_id
                    and p.get("symbol") == symbol
                    and p.get("horizon_days") == horizon
                )
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
    # Horizons for decoupled market calls. Short windows resolve fast, so
    # independent (non-overlapping) samples accumulate in weeks, not months.
    HORIZONS = [5, 30]

    def _has_open(self, symbol: str, horizon: int | None) -> dict | None:
        for existing in self.load_open():
            if existing.get("symbol") != symbol:
                continue
            # A symbol-only match (horizon=None) blocks any open bet on the name;
            # a horizon match blocks only the same window.
            if horizon is None or existing.get("horizon_days") == horizon:
                return existing
        return None

    def create_from_trade(self, trade, confidence: float, spy_price: float) -> dict:
        # One open prediction per symbol at a time. Buying the same name across
        # several runs (or an early run that recorded no run_id) must not stack
        # overlapping "X will outperform SPY over 30 days" bets — that inflates the
        # count and produces the redundant rows on the predictions page. A fresh
        # prediction only opens once the prior one for this symbol has resolved.
        existing = self._has_open(trade.symbol, horizon=None)
        if existing is not None:
            logger.info("Open prediction already tracks %s — not duplicating", trade.symbol)
            return existing

        horizon = self.HORIZON_DAYS
        run_id = getattr(trade, "run_id", None)
        prediction = {
            "id": _prediction_id(run_id, trade.symbol, horizon),
            "run_id": run_id,
            "date": date.today().isoformat(),
            "symbol": trade.symbol,
            "prediction": f"{trade.symbol} will outperform SPY over {horizon} days",
            "direction": "OUTPERFORM",
            "thesis": getattr(trade, "reasoning", "") or "",
            "horizon_days": horizon,
            "confidence": confidence,
            "became_trade": True,
            "start_price": trade.price,
            "spy_start_price": spy_price,
            "due_date": (date.today() + timedelta(days=horizon)).isoformat(),
            "status": "open",
            "result": None,
        }
        self.save(prediction)
        return prediction

    def create_call(
        self,
        *,
        run_id: str | None,
        symbol: str,
        direction: str,
        confidence: float,
        thesis: str,
        start_price: float,
        spy_price: float,
        horizon: int,
        became_trade: bool = False,
    ) -> dict | None:
        # Independence guard: one OPEN prediction per (symbol, horizon). A fresh
        # window only opens once the prior one for that horizon has resolved, so
        # windows never overlap — daily calls on the same name don't stack into
        # autocorrelated rows that inflate N past the effective sample size.
        if self._has_open(symbol, horizon) is not None:
            return None

        direction = (direction or "OUTPERFORM").upper()
        verb = "outperform" if direction == "OUTPERFORM" else "underperform"
        prediction = {
            "id": _prediction_id(run_id, symbol, horizon),
            "run_id": run_id,
            "date": date.today().isoformat(),
            "symbol": symbol,
            "prediction": f"{symbol} will {verb} SPY over {horizon} days",
            "direction": direction,
            "thesis": thesis or "",
            "horizon_days": horizon,
            "confidence": confidence,
            "became_trade": became_trade,
            "start_price": start_price,
            "spy_start_price": spy_price,
            "due_date": (date.today() + timedelta(days=horizon)).isoformat(),
            "status": "open",
            "result": None,
        }
        self.save(prediction)
        return prediction
