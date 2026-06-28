from dataclasses import dataclass, field
from typing import Any


@dataclass
class PortfolioRunState:
    run_id: str
    started_at: str
    portfolio_store: Any | None = None
    trade_store: Any | None = None
    engine: Any | None = None
    market_data: Any | None = None
    news_client: Any | None = None
    benchmark_client: Any | None = None
    research: dict = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    memory_result: Any | None = None
    memory_context: list[dict] = field(default_factory=list)
    decisions: dict = field(default_factory=dict)
    risk_review: Any | None = None
    rebalance_result: Any | None = None
    approved_trades: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    snapshot: Any | None = None
    report_markdown: str = ""
    tweet: str = ""
    run_status: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_step: str | None = None
