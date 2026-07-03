# AI Portfolio Manager

An AI-powered portfolio management system that uses LLM agents to analyze markets, manage a simulated portfolio, and generate reports.

## Features

- **Analyst Debate**: Bull, bear, and risk analyst agents each argue a structured thesis; the portfolio manager synthesizes them and must explicitly respond to the bear case. The full debate transcript is journaled and shown on the dashboard.
- **Portfolio Management Agent**: Makes buy/sell/hold decisions based on market data and news
- **Research Agent**: Gathers and synthesizes market data, news, and sentiment
- **Tweet Generator**: Creates social media content about portfolio performance
- **Simulated Trading**: Paper trading engine with full position tracking
- **Reporting**: Markdown and HTML performance reports
- **Benchmarking**: Compare portfolio performance against S&P 500 and other indices
- **Prediction Calibration**: Every BUY spawns a 30-day "beat SPY" prediction; the dashboard scores them and reports a Brier score and confidence-calibration curve (predicted confidence vs. observed win rate)
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
make eval
make run
make dashboard PORT=8001
make ingest-memory
make status
```

The daily cycle runs as a LangGraph workflow (`src/workflows/daily_graph.py`); `make run` and the scheduled GitHub Action both invoke it via `scripts/daily_run.py`.

### Decision Evals

`make eval` runs the portfolio manager against golden scenarios in `evals/` (bull
market, crash, high cash, overconcentration, missing data, stale memory) and scores
each decision with deterministic scorers (schema validity, risk compliance, citation
validity) plus an optional LLM-as-judge grounding check. Results are persisted to
`data/eval_results.jsonl` with the model and prompt version. A GitHub Action
(`.github/workflows/evals.yml`) runs the evals at temperature 0 on pull requests that
touch prompts, schemas, or the agent — so a change that breaks the prompt fails CI.
Running live needs `OPENAI_API_KEY`; the scorers and runner are fully unit-tested
without one.

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
retrieval status, number of trades executed, warning count, and per-run LLM
cost. Every run's final status is also appended to a durable history
(`data/run_history.jsonl`, exported to `public/run_history.json`) so run history
survives across runs rather than only showing the latest.

Per-run LLM cost/latency is aggregated from the gateway's call log (each call is
tagged with its `run_id`) and included in `run_status.json` under `llm`.

### LLM Tracing (optional)

Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to trace each run to
[Langfuse](https://langfuse.com): one trace per run, with a span per graph node
and a generation (model, tokens, cost) per LLM call. Without the keys, tracing is
a silent no-op and never affects a run.

### Analyst Debate

The decision step runs a mini investment committee: `BullAnalyst`, `BearAnalyst`,
and `RiskAnalyst` (`src/agents/analysts.py`) each produce a structured thesis on the
cheap model tier, then the portfolio manager (strong tier) synthesizes them into the
final decision and must fill a `bear_case_response` addressing each major bear point.
The debate transcript is embedded in the decision, stored in the journal, and
rendered on the decisions dashboard. See `src/agents/debate.py`.

### Model Routing & Fallback

Every LLM call is routed by **tier** through a provider abstraction
(`src/llm/providers/`, `src/llm/routing.py`): the **strong** tier serves final
decisions, PM synthesis, and judges; the **cheap** tier serves analysts, summaries,
and tweets. Each tier resolves to a `(provider, model)` route. Setting
`LLM_STRONG_MODEL` to a pricier model (e.g. `gpt-4o`) while `LLM_CHEAP_MODEL` stays
`gpt-4o-mini` makes the split reduce per-run cost vs. running everything on the
strong model. If `LLM_FALLBACK_PROVIDER` / `LLM_FALLBACK_MODEL` are set, a call that
exhausts retries on its primary route falls back to that route before failing; the
cost log records the serving `provider` and whether it `fell_back`. Only OpenAI
ships today — the interface is provider-agnostic so others slot in.

### Grounding Check

Before a decision is journaled and tweeted, an LLM-as-judge grounding check
(`src/scoring/grounding.py`) verifies its factual claims (prices, returns, news,
memory references) against the context the manager actually had. Findings are
stored on the decision journal entry under `grounding`, and a flagged decision
**blocks tweeting** (`tweet_publish.status = "blocked_grounding"`) so the fund never
posts unsupported claims. If the judge is unavailable the check degrades to
`unavailable` (non-blocking) rather than failing the run. The judge shares its
schema with the offline eval harness (`evals/grounding.py`).

### Human-in-the-Loop Approval

By default (`AUTO_APPROVE=true`) the daily cycle runs unattended. Set
`AUTO_APPROVE=false` to insert a human approval gate after risk review and before
execution: the run prints the pending trades and prompts you in the terminal to
approve all, reject all, or edit down to a chosen subset. The decision is recorded
in `run_status.human_review`. (This gate is in-process; the run must stay open for
approval. Durable cross-process approval is a planned follow-up.)

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
