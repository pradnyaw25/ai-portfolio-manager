"""Golden scenarios for decision evals.

Each scenario is a fixture of inputs to ``PortfolioManagerAgent.decide`` plus the
expectations the deterministic scorers check. Symbols with a non-null price are
the tradable universe; a decision that trades anything else fails risk compliance.
"""

from dataclasses import dataclass, field


@dataclass
class Scenario:
    name: str
    description: str
    portfolio: dict
    research: dict
    benchmark: dict
    memory: list[dict] = field(default_factory=list)
    cash_pct: float = 0.1
    expects_cash_thesis: bool = False
    expects_debate: bool = False

    def tradable_symbols(self) -> list[str]:
        symbols = []
        for entry in self.research.get("symbols", []):
            if entry.get("price") is not None:
                symbols.append(str(entry["symbol"]).upper())
        return symbols


def _symbols(*pairs) -> list[dict]:
    return [{"symbol": s, "price": p, "return_5d": r5, "return_30d": r30} for s, p, r5, r30 in pairs]


BULL_MARKET = Scenario(
    name="bull_market",
    description="Healthy uptrend, moderate cash — normal buy/hold decisions expected.",
    portfolio={"total_value": 1_000_000, "cash": 120_000, "cash_pct": 0.12, "positions": [
        {"symbol": "AAPL", "shares": 300, "avg_cost": 180, "current_price": 205},
    ]},
    research={"symbols": _symbols(
        ("AAPL", 205.0, 0.03, 0.09), ("MSFT", 430.0, 0.02, 0.07),
        ("NVDA", 140.0, 0.05, 0.15), ("SPY", 560.0, 0.01, 0.04),
    ), "market_news": [{"title": "Markets extend rally on strong earnings"}]},
    benchmark={"return_pct": 0.04, "current": 560.0},
    cash_pct=0.12,
)

MARKET_CRASH = Scenario(
    name="market_crash",
    description="Sharp drawdown, elevated volatility — caution and risk framing expected.",
    portfolio={"total_value": 850_000, "cash": 170_000, "cash_pct": 0.20, "positions": [
        {"symbol": "NVDA", "shares": 500, "avg_cost": 160, "current_price": 120},
    ]},
    research={"symbols": _symbols(
        ("AAPL", 170.0, -0.08, -0.14), ("MSFT", 360.0, -0.07, -0.12),
        ("NVDA", 120.0, -0.12, -0.25), ("SPY", 480.0, -0.09, -0.16),
    ), "market_news": [{"title": "Stocks plunge as recession fears mount"}]},
    benchmark={"return_pct": -0.16, "current": 480.0},
    cash_pct=0.20,
)

HIGH_CASH = Scenario(
    name="high_cash",
    description="Cash well above the 25% target — must deploy or justify with a cash thesis.",
    portfolio={"total_value": 1_000_000, "cash": 450_000, "cash_pct": 0.45, "positions": [
        {"symbol": "MSFT", "shares": 400, "avg_cost": 400, "current_price": 430},
    ]},
    research={"symbols": _symbols(
        ("AAPL", 205.0, 0.02, 0.06), ("MSFT", 430.0, 0.01, 0.05),
        ("V", 285.0, 0.01, 0.03), ("SPY", 560.0, 0.01, 0.04),
    ), "market_news": [{"title": "Calm markets, low volatility"}]},
    benchmark={"return_pct": 0.04, "current": 560.0},
    cash_pct=0.45,
    expects_cash_thesis=True,
)

OVERCONCENTRATION = Scenario(
    name="overconcentration",
    description="Portfolio heavily concentrated in one name — diversification awareness expected.",
    portfolio={"total_value": 1_000_000, "cash": 80_000, "cash_pct": 0.08, "positions": [
        {"symbol": "NVDA", "shares": 6000, "avg_cost": 130, "current_price": 140},
    ]},
    research={"symbols": _symbols(
        ("NVDA", 140.0, 0.04, 0.12), ("AAPL", 205.0, 0.02, 0.06),
        ("MSFT", 430.0, 0.02, 0.05), ("SPY", 560.0, 0.01, 0.04),
    ), "market_news": [{"title": "Chip stocks lead gains"}]},
    benchmark={"return_pct": 0.04, "current": 560.0},
    cash_pct=0.08,
)

MISSING_DATA = Scenario(
    name="missing_data",
    description="Some symbols have no price — the agent must not invent prices or trade them.",
    portfolio={"total_value": 1_000_000, "cash": 150_000, "cash_pct": 0.15, "positions": []},
    research={"symbols": [
        {"symbol": "AAPL", "price": 205.0, "return_5d": 0.02, "return_30d": 0.06},
        {"symbol": "MSFT", "price": None, "return_5d": None, "return_30d": None},
        {"symbol": "TSLA", "price": None, "return_5d": None, "return_30d": None},
        {"symbol": "SPY", "price": 560.0, "return_5d": 0.01, "return_30d": 0.04},
    ], "market_news": []},
    benchmark={"return_pct": 0.04, "current": 560.0},
    cash_pct=0.15,
)

STALE_MEMORY = Scenario(
    name="stale_memory",
    description="An old, now-contradicted thesis in memory — the agent shouldn't blindly follow it.",
    portfolio={"total_value": 1_000_000, "cash": 200_000, "cash_pct": 0.20, "positions": [
        {"symbol": "AAPL", "shares": 200, "avg_cost": 190, "current_price": 205},
    ]},
    research={"symbols": _symbols(
        ("AAPL", 205.0, -0.04, -0.10), ("MSFT", 430.0, 0.01, 0.04),
        ("SPY", 560.0, 0.00, 0.02),
    ), "market_news": [{"title": "Apple slips on weak guidance"}]},
    benchmark={"return_pct": 0.02, "current": 560.0},
    memory=[{
        "id": "thesis:aapl-2026-01-15",
        "type": "thesis",
        "date": "2026-01-15",
        "symbols": ["AAPL"],
        "content": "AAPL is a strong momentum buy; load up aggressively.",
    }],
    cash_pct=0.20,
)

DEBATE = Scenario(
    name="debate",
    description="Mixed signals — runs the full bull/bear/risk debate; the PM must "
    "respond to the bear case.",
    portfolio={"total_value": 1_000_000, "cash": 150_000, "cash_pct": 0.15, "positions": [
        {"symbol": "NVDA", "shares": 800, "avg_cost": 130, "current_price": 140},
    ]},
    research={"symbols": _symbols(
        ("NVDA", 140.0, 0.06, -0.03), ("AAPL", 205.0, 0.01, 0.05),
        ("MSFT", 430.0, -0.01, 0.02), ("SPY", 560.0, 0.00, 0.03),
    ), "market_news": [{"title": "Chip demand strong but valuations stretched"}]},
    benchmark={"return_pct": 0.03, "current": 560.0},
    cash_pct=0.15,
    expects_debate=True,
)

EARNINGS_CONTEXT = Scenario(
    name="earnings_context",
    description="A fresh 8-K earnings release and 10-Q MD&A are in memory — the PM "
    "can ground a view in cited earnings/filing context.",
    portfolio={"total_value": 1_000_000, "cash": 120_000, "cash_pct": 0.12, "positions": [
        {"symbol": "AAPL", "shares": 300, "avg_cost": 180, "current_price": 205},
    ]},
    research={"symbols": _symbols(
        ("AAPL", 205.0, 0.03, 0.08), ("MSFT", 430.0, 0.01, 0.05),
        ("SPY", 560.0, 0.01, 0.04),
    ), "market_news": [{"title": "Apple guides higher on services strength"}]},
    benchmark={"return_pct": 0.04, "current": 560.0},
    memory=[
        {
            "id": "earnings_event:AAPL:000032019325000123:0000",
            "type": "earnings_event",
            "date": "2026-05-01",
            "symbols": ["AAPL"],
            "source_type": "earnings_8k",
            "source_id": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000123/aapl-ex991.htm",
            "content": "Apple reported record June-quarter services revenue and issued "
            "upbeat guidance for the September quarter.",
        },
        {
            "id": "10q:AAPL:000032019325000124:item_2:0000",
            "type": "thesis",
            "date": "2026-05-02",
            "symbols": ["AAPL"],
            "source_type": "sec_10q",
            "source_id": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000124/aapl-10q.htm",
            "content": "Management attributes gross margin expansion to a favorable "
            "services mix shift and disciplined component costs.",
        },
    ],
    cash_pct=0.12,
)

SCENARIOS = [
    BULL_MARKET,
    MARKET_CRASH,
    HIGH_CASH,
    OVERCONCENTRATION,
    MISSING_DATA,
    STALE_MEMORY,
    DEBATE,
    EARNINGS_CONTEXT,
]
