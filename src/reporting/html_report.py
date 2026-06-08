from datetime import date
from jinja2 import Template
from src.config import REPORTS_DIR
from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade
from src.simulator.performance import PerformanceTracker
from src.utils.logger import get_logger

logger = get_logger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Portfolio Report — {{ date }}</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
        h1 { border-bottom: 2px solid #333; padding-bottom: 0.5rem; }
        table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
        th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: right; }
        th { background: #f5f5f5; }
        td:first-child, th:first-child { text-align: left; }
        .positive { color: #16a34a; }
        .negative { color: #dc2626; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
        .card { background: #f9fafb; border-radius: 8px; padding: 1rem; }
        .card .value { font-size: 1.5rem; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Portfolio Report — {{ date }}</h1>
    <div class="summary">
        <div class="card"><div class="label">Total Value</div><div class="value">${{ "%.2f"|format(total_value) }}</div></div>
        <div class="card"><div class="label">Cash</div><div class="value">${{ "%.2f"|format(cash) }}</div></div>
        <div class="card"><div class="label">Positions</div><div class="value">{{ num_positions }}</div></div>
    </div>
    <h2>Holdings</h2>
    <table>
        <tr><th>Symbol</th><th>Shares</th><th>Avg Cost</th><th>Current</th><th>P&L %</th></tr>
        {% for p in positions %}
        <tr>
            <td>{{ p.symbol }}</td>
            <td>{{ p.shares }}</td>
            <td>${{ "%.2f"|format(p.avg_cost) }}</td>
            <td>${{ "%.2f"|format(p.current_price) }}</td>
            <td class="{{ 'positive' if p.return_pct >= 0 else 'negative' }}">{{ "%.1f"|format(p.return_pct * 100) }}%</td>
        </tr>
        {% endfor %}
    </table>
    <h2>Today's Trades</h2>
    {% if trades %}
    <ul>
        {% for t in trades %}
        <li><strong>{{ t.action.value }}</strong> {{ t.shares }} {{ t.symbol }} @ ${{ "%.2f"|format(t.price) }}</li>
        {% endfor %}
    </ul>
    {% else %}
    <p>No trades executed today.</p>
    {% endif %}
</body>
</html>"""


class HtmlReportGenerator:
    def generate(self, portfolio: PortfolioSnapshot, trades: list[Trade]) -> str:
        template = Template(HTML_TEMPLATE)
        html = template.render(
            date=portfolio.date,
            total_value=portfolio.total_value,
            cash=portfolio.cash,
            num_positions=len(portfolio.positions),
            positions=sorted(portfolio.positions, key=lambda x: x.market_value, reverse=True),
            trades=trades,
        )

        filename = f"report_{date.today().isoformat()}.html"
        filepath = REPORTS_DIR / filename
        filepath.write_text(html)
        logger.info("Generated HTML report: %s", filepath)
        return html
