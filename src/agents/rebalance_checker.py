import json
from dataclasses import dataclass

from openai import OpenAI

from src.agents.risk_manager import RiskManagerAgent
from src.config import TARGET_CASH_PCT, REBALANCE_MIN_DEPLOY_PCT, REBALANCE_TURNOVER
from src.models.portfolio import PortfolioSnapshot
from src.models.prediction import TradePrediction
from src.utils.logger import get_logger

logger = get_logger(__name__)

client = OpenAI()


@dataclass
class RebalanceResult:
    extra_trades: list[TradePrediction]
    cash_thesis: str | None


class RebalanceChecker:
    """Post-risk-review gate that enforces cash deployment or demands justification."""

    def check(
        self,
        portfolio: PortfolioSnapshot,
        approved_trades: list[TradePrediction],
        prices: dict[str, float],
        research: dict,
    ) -> RebalanceResult:
        projected_cash = self._project_cash(portfolio, approved_trades, prices)
        projected_total = portfolio.total_value
        projected_cash_pct = projected_cash / projected_total if projected_total > 0 else 0.0

        if projected_cash_pct <= TARGET_CASH_PCT:
            logger.info(
                "Cash projected at %.1f%% after approved trades — within target, no rebalance needed",
                projected_cash_pct * 100,
            )
            return RebalanceResult(extra_trades=[], cash_thesis=None)

        logger.info(
            "Cash projected at %.1f%% after approved trades — exceeds %.0f%% target, triggering rebalance",
            projected_cash_pct * 100,
            TARGET_CASH_PCT * 100,
        )

        excess_cash = projected_cash - (projected_total * TARGET_CASH_PCT)
        min_deploy = projected_total * REBALANCE_MIN_DEPLOY_PCT

        if excess_cash < min_deploy:
            logger.info("Excess cash $%.2f below minimum deployment $%.2f — skipping", excess_cash, min_deploy)
            return RebalanceResult(extra_trades=[], cash_thesis=None)

        return self._request_deployment(portfolio, projected_cash_pct, excess_cash, prices, research)

    def _project_cash(
        self,
        portfolio: PortfolioSnapshot,
        trades: list[TradePrediction],
        prices: dict[str, float],
    ) -> float:
        cash = portfolio.cash
        for t in trades:
            price = prices.get(t.symbol, 0)
            if t.action == "BUY":
                cash -= t.shares * price
            elif t.action == "SELL":
                cash += t.shares * price
        return cash

    def _request_deployment(
        self,
        portfolio: PortfolioSnapshot,
        cash_pct: float,
        excess_cash: float,
        prices: dict[str, float],
        research: dict,
    ) -> RebalanceResult:
        holdings_summary = ", ".join(
            f"{p.symbol} ({p.shares} shares @ ${p.current_price:.2f})"
            for p in portfolio.positions
        ) or "No current holdings"

        watchlist = research.get("watchlist", [])
        movers = research.get("top_movers", [])

        per_position_budget = excess_cash / 5

        prompt = f"""
You are a portfolio rebalance assistant. The portfolio has too much cash and needs to deploy it.

Current state:
- Cash: ${portfolio.cash:,.2f} ({cash_pct * 100:.1f}% of portfolio)
- Target maximum cash: {TARGET_CASH_PCT * 100:.0f}%
- Excess cash to deploy: ${excess_cash:,.2f}
- Current holdings: {holdings_summary}
- Total portfolio value: ${portfolio.total_value:,.2f}

Watchlist: {watchlist}
Recent top movers: {json.dumps(movers[:5])}
Market news: {json.dumps(research.get("market_news", [])[:3])}

CRITICAL SIZING RULES:
- You must deploy approximately ${excess_cash:,.0f} total across your trades.
- Split into 4-6 positions, each approximately ${per_position_budget:,.0f}.
- Calculate shares as: shares = floor(${per_position_budget:,.0f} / stock_price).
- Example: If AAPL is $200, buy {int(per_position_budget / 200)} shares (${per_position_budget:,.0f} / $200).
- Example: If NVDA is $140, buy {int(per_position_budget / 140)} shares (${per_position_budget:,.0f} / $140).
- DO NOT propose single-digit share counts for stocks under $500. That deploys too little cash.

Available prices:
{json.dumps({s: p for s, p in prices.items() if s in (watchlist if watchlist else list(prices.keys())[:20])}, indent=2)}

You MUST do exactly one of these:

OPTION A — Deploy cash: Propose BUY trades totaling ~${excess_cash:,.0f}.
  - Include confidence scores (0.0-1.0) and reasoning

OPTION B — Justify cash: If there is a compelling macro reason to hold cash above target
  (imminent recession, market crash, extreme valuations, pending black swan),
  write a detailed cash_thesis. "Being cautious" is NOT sufficient.

Return ONLY valid JSON:
{{
  "action": "deploy" or "hold_cash",
  "trades": [
    {{"symbol": "AAPL", "action": "BUY", "shares": {int(per_position_budget / 200)}, "confidence": 0.75, "reason": "..."}}
  ],
  "cash_thesis": null or "detailed justification..."
}}
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        cash_thesis = result.get("cash_thesis")

        if result.get("action") == "hold_cash" and cash_thesis:
            logger.info("Rebalance: AI chose to hold cash — thesis: %s", cash_thesis[:120])
            return RebalanceResult(extra_trades=[], cash_thesis=cash_thesis)

        raw_trades = result.get("trades", [])
        if not raw_trades:
            logger.warning("Rebalance: AI returned no trades and no cash thesis — forcing cash thesis")
            return RebalanceResult(
                extra_trades=[],
                cash_thesis="[AUTO] AI failed to deploy cash or provide justification during rebalance check.",
            )

        risk_manager = RiskManagerAgent()
        review = risk_manager.review(
            raw_trades=raw_trades,
            portfolio=portfolio,
            prices=prices,
            turnover_override=REBALANCE_TURNOVER,
        )

        if review.rejected:
            logger.info(
                "Rebalance: %d trades rejected by risk manager: %s",
                len(review.rejected),
                [(r.symbol, r.reason) for r in review.rejected],
            )

        logger.info("Rebalance: %d additional trades approved for cash deployment", len(review.approved))

        estimated_deploy = sum(
            trade.shares * prices[trade.symbol]
            for trade in review.approved
            if trade.symbol in prices
        )

        logger.info(
            "Rebalance proposed deployment: $%.2f across %d trades",
            estimated_deploy,
            len(review.approved),
        )

        required_deploy = portfolio.total_value * (cash_pct - TARGET_CASH_PCT)

        max_deployable = portfolio.total_value * REBALANCE_TURNOVER
        required_deploy = min(required_deploy, max_deployable)

        if estimated_deploy < required_deploy * 0.3:
            logger.warning(
                "Rebalance rejected: proposed deployment $%.2f is too small vs required $%.2f",
                estimated_deploy,
                required_deploy,
            )
            return RebalanceResult(
                extra_trades=[],
                cash_thesis="[AUTO] Rebalance trades were too small to meaningfully reduce cash position.",
            )

        return RebalanceResult(extra_trades=review.approved, cash_thesis=cash_thesis)
