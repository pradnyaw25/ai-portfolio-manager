import pandas as pd
from src.config import DATA_DIR
from src.models.portfolio import PortfolioSnapshot
from src.utils.logger import get_logger

logger = get_logger(__name__)

HISTORY_FILE = DATA_DIR / "portfolio_history.csv"


class PerformanceTracker:
    def record(self, snapshot: PortfolioSnapshot) -> None:
        history = self._load_history()
        today = snapshot.date.isoformat()

        # Upsert: drop any existing row(s) for today so reruns don't pile up.
        if not history.empty and "date" in history.columns:
            history = history[history["date"].astype(str) != today]

        # prev_value is the most recent *prior* day; first_value is inception.
        prev_value = history["total_value"].iloc[-1] if not history.empty else snapshot.total_value
        daily_return = (snapshot.total_value / prev_value) - 1 if prev_value > 0 else 0.0

        first_value = history["total_value"].iloc[0] if not history.empty else snapshot.total_value
        cumulative_return = (snapshot.total_value / first_value) - 1 if first_value > 0 else 0.0

        new_row = pd.DataFrame([{
            "date": today,
            "total_value": snapshot.total_value,
            "cash": snapshot.cash,
            "invested": snapshot.invested_value,
            "daily_return": daily_return,
            "cumulative_return": cumulative_return,
        }])

        history = pd.concat([history, new_row], ignore_index=True)
        history.to_csv(HISTORY_FILE, index=False)
        logger.info("Recorded performance: value=$%.2f, daily=%.2f%%", snapshot.total_value, daily_return * 100)

    def get_history(self) -> pd.DataFrame:
        return self._load_history()

    def get_stats(self) -> dict:
        history = self._load_history()
        if history.empty:
            return {}

        returns = history["daily_return"].dropna()
        return {
            "total_return": float(history["cumulative_return"].iloc[-1]),
            "avg_daily_return": float(returns.mean()),
            "volatility": float(returns.std()),
            "max_drawdown": self._max_drawdown(history["total_value"]),
            "sharpe_ratio": self._sharpe_ratio(returns),
            "days_tracked": len(history),
        }

    def _load_history(self) -> pd.DataFrame:
        try:
            df = pd.read_csv(HISTORY_FILE)
            return df if not df.empty else pd.DataFrame()
        except (FileNotFoundError, pd.errors.EmptyDataError):
            return pd.DataFrame()

    def _max_drawdown(self, values: pd.Series) -> float:
        peak = values.expanding().max()
        drawdown = (values - peak) / peak
        return float(drawdown.min()) if not drawdown.empty else 0.0

    def _sharpe_ratio(self, returns: pd.Series, risk_free_rate: float = 0.05) -> float:
        if returns.empty or returns.std() == 0:
            return 0.0
        daily_rf = (1 + risk_free_rate) ** (1 / 252) - 1
        excess = returns - daily_rf
        return float(excess.mean() / excess.std() * (252 ** 0.5))
