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
    memory_groups: dict[str, list[dict]] = field(default_factory=dict)
    research_brief: dict | None = None
    decisions: dict = field(default_factory=dict)
    grounding: dict | None = None
    risk_review: Any | None = None
    rebalance_result: Any | None = None
    approved_trades: list = field(default_factory=list)
    human_review: dict | None = None
    trades: list = field(default_factory=list)
    snapshot: Any | None = None
    report_markdown: str = ""
    tweet: str = ""
    run_status: dict = field(default_factory=dict)
    tweet_publish_result: Any | None = None
    # Predictions that resolved during THIS run (from the scorer), used to post a
    # receipts tweet. Freshly-scored-this-run, so the day's second run — which scores
    # nothing new — posts no duplicate.
    scored_predictions: list = field(default_factory=list)
    receipts_publish_result: Any | None = None
    spotlight_publish_result: Any | None = None
    memory_ingestion_result: Any | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_step: str | None = None
    # Notes on conditional-routing decisions (empty decision, no approved trades,
    # memory unavailable, execution failure), surfaced in run_status.
    diagnostics: dict = field(default_factory=dict)
    # Durable progress tracking for crash recovery (P1-2). ``resumed`` is True when
    # re-entering a run that a prior process left unfinished.
    progress: Any | None = None
    resumed: bool = False
