# AI Portfolio Manager

An AI-powered portfolio management system that uses LLM agents to analyze markets, manage a simulated portfolio, and generate reports.

## Features

- **Portfolio Management Agent**: Makes buy/sell/hold decisions based on market data and news
- **Research Agent**: Gathers and synthesizes market data, news, and sentiment
- **Tweet Generator**: Creates social media content about portfolio performance
- **Simulated Trading**: Paper trading engine with full position tracking
- **Reporting**: Markdown and HTML performance reports
- **Benchmarking**: Compare portfolio performance against S&P 500 and other indices
- **Public Dashboard**: Static HTML dashboard with portfolio, run status, prediction accuracy, and decision journal views, including last-updated metadata

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

## Local Commands

Common local workflows are available through `make`:

```bash
make test
make run
make run-graph
make dashboard PORT=8001
make ingest-memory
make status
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

## Automation

GitHub Actions runs the portfolio cycle hourly on weekdays during a broad UTC window. A market-hours guard keeps scheduled runs inside regular US market hours (9:30am-4:00pm America/New_York). Manual workflow dispatches always run.

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

If Qdrant or embeddings are unavailable, the daily cycle logs the failure, records
`memory_status="unavailable"` and `memory_error` in the decision journal, and
continues without memory context.

### Run Observability

Each daily cycle generates a `run_id` and records it in the decision journal,
executed trades, prediction records created from trades, generated reports, and
public exports. The latest run status is exported to:

```bash
public/run_status.json
```

The public dashboard displays the latest run status, completion time, memory
retrieval status, number of trades executed, and warning count.

Do not commit `.env` or real API keys.

## Roadmap

The full assessment and phased roadmap live in [docs/ROADMAP.md](docs/ROADMAP.md), with delegation-ready task specs in [.claude/TODO.md](.claude/TODO.md). The phases, in order:

0. **Harden the foundation** — an LLM gateway with Pydantic-validated structured outputs, retries, configurable models, and idempotent stores.
1. **Orchestration & observability** — promote the LangGraph runner to the default path, add checkpointing, conditional routing, a human-in-the-loop approval gate before execution, and Langfuse tracing with cost tracking.
2. **Evals & calibration** — golden-scenario decision evals in CI, grounding checks before journaling, and Brier-score/calibration dashboards for prediction accuracy.
3. **Multi-agent & tools** — bull/bear/risk analyst debate with recorded transcripts, typed tool calling for research, and cheap-vs-strong model routing.
4. **Knowledge layer** — chunked, metadata-filtered RAG over SEC filings and earnings transcripts, plus a weekly lessons-learned reflection agent.
5. **Surface & reach** — an MCP server exposing the fund, Risk Engine V2 (sector limits, stop-loss/take-profit), and a weekly investor letter.

## License

MIT
