import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CONFIG_DIR = PROJECT_ROOT / "config"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "fund_memory")
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "ai-portfolio-manager contact@example.com",
)
POST_TWEET = os.getenv("POST_TWEET", "false").lower() in {"1", "true", "yes"}
X_API_KEY = os.getenv("X_API_KEY", "")
X_API_SECRET = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET", "")

INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "1000000"))
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.10"))

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

# LLM gateway configuration. Models are split into a "strong" tier (final
# decisions) and a "cheap" tier (summaries, tweets). Both default to the same
# model today; real routing between them is a later roadmap item (P3-3).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_STRONG_MODEL = os.getenv("LLM_STRONG_MODEL", "gpt-4o-mini")
LLM_CHEAP_MODEL = os.getenv("LLM_CHEAP_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "1.0"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
LLM_CALL_LOG = DATA_DIR / "llm_calls.jsonl"

SUPPORTED_LLM_PROVIDERS = {"openai"}

# Observability. Langfuse tracing is optional: enabled only when both keys are
# set, otherwise all tracing is a no-op. Run history is a durable record of every
# run's final status (not just the latest).
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
RUN_HISTORY_LOG = DATA_DIR / "run_history.jsonl"

# Human-in-the-loop approval. When AUTO_APPROVE is true (the default), the daily
# cycle runs unattended and the approval node is a pass-through — scheduled/CI
# runs are unaffected. Set AUTO_APPROVE=false to pause the run after risk review
# and prompt the operator in-process to approve/reject/edit trades before
# execution.
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "true").lower() in {"1", "true", "yes"}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

WATCHLIST_PATH = CONFIG_DIR / "watchlist.yaml"


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


def _load_watchlist() -> list[str]:
    """Load and normalize the watchlist from ``config/watchlist.yaml``."""
    if not WATCHLIST_PATH.exists():
        raise ConfigError(f"Watchlist file not found: {WATCHLIST_PATH}")
    try:
        data = yaml.safe_load(WATCHLIST_PATH.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Watchlist file is not valid YAML ({WATCHLIST_PATH}): {exc}") from exc

    symbols = data.get("symbols") if isinstance(data, dict) else None
    if not isinstance(symbols, list) or not symbols:
        raise ConfigError(
            f"Watchlist file must define a non-empty 'symbols' list ({WATCHLIST_PATH})"
        )
    # De-dupe while preserving order, uppercase, drop blanks.
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            normalized.append(symbol)
    return normalized


WATCHLIST = _load_watchlist()


def validate_config() -> None:
    """Validate configuration at startup, raising ConfigError listing all problems.

    Call this from process entrypoints so a misconfigured run fails loudly and
    immediately instead of deep inside the daily cycle.
    """
    errors: list[str] = []

    def check_fraction(name: str, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            errors.append(f"{name} must be between 0 and 1, got {value}")

    check_fraction("MAX_POSITION_SIZE", MAX_POSITION_SIZE)
    check_fraction("MIN_TRADE_CONFIDENCE", MIN_TRADE_CONFIDENCE)
    check_fraction("MAX_DAILY_TURNOVER", MAX_DAILY_TURNOVER)
    check_fraction("REBALANCE_TURNOVER", REBALANCE_TURNOVER)
    check_fraction("TARGET_CASH_PCT", TARGET_CASH_PCT)
    check_fraction("REBALANCE_MIN_DEPLOY_PCT", REBALANCE_MIN_DEPLOY_PCT)

    if INITIAL_CAPITAL <= 0:
        errors.append(f"INITIAL_CAPITAL must be positive, got {INITIAL_CAPITAL}")

    if LLM_PROVIDER not in SUPPORTED_LLM_PROVIDERS:
        errors.append(
            f"LLM_PROVIDER '{LLM_PROVIDER}' is not supported "
            f"(supported: {sorted(SUPPORTED_LLM_PROVIDERS)})"
        )
    if not LLM_STRONG_MODEL.strip():
        errors.append("LLM_STRONG_MODEL must not be empty")
    if not LLM_CHEAP_MODEL.strip():
        errors.append("LLM_CHEAP_MODEL must not be empty")
    if not 0.0 <= LLM_TEMPERATURE <= 2.0:
        errors.append(f"LLM_TEMPERATURE must be between 0 and 2, got {LLM_TEMPERATURE}")
    if LLM_MAX_RETRIES < 0:
        errors.append(f"LLM_MAX_RETRIES must be >= 0, got {LLM_MAX_RETRIES}")

    if not QDRANT_COLLECTION.strip():
        errors.append("QDRANT_COLLECTION must not be empty")

    if not BENCHMARK_SYMBOLS:
        errors.append("BENCHMARK_SYMBOLS must not be empty")

    if not WATCHLIST:
        errors.append("Watchlist must not be empty")

    if errors:
        raise ConfigError(
            "Invalid configuration:\n  - " + "\n  - ".join(errors)
        )
