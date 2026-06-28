import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "ai-portfolio-manager contact@example.com",
)

INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "1000000"))
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.10"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "20"))

MIN_TRADE_CONFIDENCE = float(os.getenv("MIN_TRADE_CONFIDENCE", "0.60"))
MAX_DAILY_TURNOVER = float(os.getenv("MAX_DAILY_TURNOVER", "0.20"))
REBALANCE_TURNOVER = float(os.getenv("REBALANCE_TURNOVER", "0.75"))
TARGET_CASH_PCT = float(os.getenv("TARGET_CASH_PCT", "0.25"))
REBALANCE_MIN_DEPLOY_PCT = float(os.getenv("REBALANCE_MIN_DEPLOY_PCT", "0.05"))

BENCHMARK_SYMBOLS = [
    s.strip()
    for s in os.getenv("BENCHMARK_SYMBOLS", "SPY,QQQ").split(",")
    if s.strip()
]

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
