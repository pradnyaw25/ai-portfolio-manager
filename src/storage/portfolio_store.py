import json
from pathlib import Path
from datetime import date
from src.config import DATA_DIR
from src.models.portfolio import PortfolioSnapshot, Position
from src.utils.logger import get_logger

logger = get_logger(__name__)

PORTFOLIO_FILE = DATA_DIR / "portfolio_state.json"


class PortfolioStore:
    def save(self, snapshot: PortfolioSnapshot) -> None:
        data = {
            "date": snapshot.date.isoformat(),
            "cash": snapshot.cash,
            "positions": [
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                }
                for p in snapshot.positions
            ],
        }
        PORTFOLIO_FILE.write_text(json.dumps(data, indent=2))
        logger.info("Saved portfolio state")

    def load(self) -> PortfolioSnapshot | None:
        if not PORTFOLIO_FILE.exists():
            return None
        try:
            data = json.loads(PORTFOLIO_FILE.read_text())
            positions = [
                Position(
                    symbol=p["symbol"],
                    shares=p["shares"],
                    avg_cost=p["avg_cost"],
                    current_price=p.get("current_price", 0),
                )
                for p in data.get("positions", [])
            ]
            return PortfolioSnapshot(
                date=date.fromisoformat(data["date"]),
                cash=data["cash"],
                positions=positions,
            )
        except Exception as e:
            logger.error("Failed to load portfolio: %s", e)
            return None
