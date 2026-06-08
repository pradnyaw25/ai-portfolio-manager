from datetime import date
from src.config import REPORTS_DIR
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade
from src.models.prediction import PortfolioDecision
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarkdownReportGenerator:
    def generate(
        self,
        portfolio: PortfolioSnapshot,
        trades: list[Trade],
        research: dict,
        decision: PortfolioDecision,
    ) -> str:
        report = self._build_report(portfolio, trades, research, decision)
        filename = f"report_{date.today().isoformat()}.md"
        filepath = REPORTS_DIR / filename
        filepath.write_text(report)
        logger.info("Generated report: %s", filepath)
        return report

    def _build_report(
        self,
        portfolio: PortfolioSnapshot,
        trades: list[Trade],
        research: dict,
        decision: PortfolioDecision,
    ) -> str:
        lines = [
            f"# Portfolio Report — {portfolio.date}",
            "",
            "## Summary",
            f"- **Total Value:** ${portfolio.total_value:,.2f}",
            f"- **Cash:** ${portfolio.cash:,.2f} ({portfolio.cash_pct:.1%})",
            f"- **Invested:** ${portfolio.invested_value:,.2f}",
            f"- **Positions:** {len(portfolio.positions)}",
            f"- **Outlook:** {decision.outlook.value}",
            "",
            "## Holdings",
            "",
            "| Symbol | Shares | Avg Cost | Current | P&L % |",
            "|--------|--------|----------|---------|-------|",
        ]

        for p in sorted(portfolio.positions, key=lambda x: x.market_value, reverse=True):
            lines.append(
                f"| {p.symbol} | {p.shares:.0f} | ${p.avg_cost:.2f} | "
                f"${p.current_price:.2f} | {p.return_pct:.1%} |"
            )

        lines.extend(["", "## Today's Trades", ""])
        if trades:
            for t in trades:
                lines.append(
                    f"- **{t.action.value}** {t.shares:.0f} {t.symbol} "
                    f"@ ${t.price:.2f} — {t.reasoning}"
                )
        else:
            lines.append("No trades executed today.")

        lines.extend([
            "",
            "## Analysis",
            "",
            decision.reasoning,
            "",
            "## Risk Assessment",
            "",
            decision.risk_assessment,
        ])

        return "\n".join(lines)
