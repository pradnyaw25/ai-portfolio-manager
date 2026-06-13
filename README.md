# AI Portfolio Manager

An AI-powered portfolio management system that uses LLM agents to analyze markets, manage a simulated portfolio, and generate reports.

## Features

- **Portfolio Management Agent**: Makes buy/sell/hold decisions based on market data and news
- **Research Agent**: Gathers and synthesizes market data, news, and sentiment
- **Tweet Generator**: Creates social media content about portfolio performance
- **Simulated Trading**: Paper trading engine with full position tracking
- **Reporting**: Markdown and HTML performance reports
- **Benchmarking**: Compare portfolio performance against S&P 500 and other indices
- **Public Dashboard**: Static HTML dashboard with portfolio, prediction, and decision journal views

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```
4. Run the daily portfolio update:
   ```bash
   python scripts/daily_run.py
   ```

## Project Structure

```
src/
  agents/          - LLM-powered agents (portfolio manager, researcher, tweet writer)
  data_sources/    - Market data, news, and benchmark fetchers
  models/          - Data models (portfolio, trade, prediction)
  simulator/       - Portfolio engine and performance tracking
  reporting/       - Markdown and HTML report generation
  storage/         - CSV-based persistence layer
  utils/           - Logging and date helpers
scripts/           - CLI entry points (daily run, backfill, benchmark)
tests/             - Unit tests
public/            - Static dashboard exports for portfolio, predictions, and decisions
web/               - Frontend dashboard experiments
```

## Configuration

All configuration is managed via environment variables. See `.env.example` for required keys.

### Qdrant Memory Store

The memory layer uses Qdrant for vector search over prior reports. By default, local development uses:

```bash
QDRANT_URL=http://localhost:6333
```

To run Qdrant locally:

```bash
docker run -p 6333:6333 qdrant/qdrant
```

Then ingest existing reports:

```bash
python -m src.memory.ingest
```

For Qdrant Cloud, set both values in `.env`:

```bash
QDRANT_URL=https://your-cluster-url
QDRANT_API_KEY=your-qdrant-cloud-api-key
```

Do not commit `.env` or real API keys.

## License

MIT
