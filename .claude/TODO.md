# AI Portfolio Manager Roadmap

This list tracks open engineering work only, organized into phases. Each task is
scoped so an independent coding agent can execute it: inputs, outputs, and
acceptance criteria are explicit. Rationale, architecture, and the
not-worth-building list live in `docs/ROADMAP.md`.

Execution order: phases are sequential; tasks marked ∥ can run in parallel within
their phase. Tasks assume the `.venv` environment and `make test` green before/after.

## Phase 0 — Harden the Foundation (~1 week)

Goal: kill the fragility before building on it. Everything later flows through P0-1.

### P0-1. Create the LLM gateway
* Input: the three existing LLM call sites (`src/agents/portfolio_manager.py`,
  `src/agents/rebalance_checker.py`, `src/agents/tweet_generator.py`).
* Output: `src/llm/gateway.py` exposing `complete(prompt, schema: type[BaseModel], model_tier)`:
  * Pydantic validation of every LLM response; one repair-retry on invalid output
    (re-prompt with the validation error).
  * Exponential backoff retry on transient API errors.
  * Model, provider, and temperature resolved from config (per tier: `cheap` / `strong`).
  * Per-call log of model, prompt version, tokens, latency, and estimated cost.
* Migrate all three agents onto the gateway with per-agent Pydantic response schemas.
* Acceptance: no raw `json.loads` on LLM output anywhere in `src/`; a test with a
  mocked malformed response proves the repair path; a mocked API error proves backoff.

### P0-2 ∥. Config consolidation and dead-code removal
* Output:
  * Model names/tiers, temperature, watchlist, and Qdrant collection name in typed
    config, validated at startup with clear errors. Watchlist moves from
    `src/research/market_context.py` to a YAML file (also used by
    `scripts/ingest_sec_filings.py`).
  * Delete `src/agents/researcher.py` (dead code) and unused config keys
    (`ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `MAX_POSITIONS`).
  * Remove unused dependencies (`plotly`, `anthropic` until the gateway uses it).
* Acceptance: `grep -r "gpt-4o-mini" src/` returns nothing; startup fails loudly on
  invalid config; tests green.

### P0-3 ∥. Idempotent stores
* Input: `src/storage/` (trades CSV, decisions JSONL, predictions JSONL).
* Output: writes keyed by (run_id, symbol/date) with upsert semantics instead of
  blind append.
* Acceptance: running the daily cycle twice with the same run_id produces identical
  files/rows — no duplicates.

## Phase 1 — Orchestration & Observability (1–2 weeks)

Goal: LangGraph is *the* runner; every run is fully visible.

### P1-1. Graph parity and promotion — DONE
* Input: `src/workflows/daily_graph.py`, `src/main.py`.
* Output: `scripts/daily_run.py` (and the scheduled GitHub Action) invoke the graph;
  legacy runner removed (`daily_run_legacy.py`, `daily_run_graph.py`, and
  `main.py`'s `run_daily_cycle` orchestration + `__main__`); `main.py` is now a
  pure step library. Full-cycle graph integration test added.
* Note: byte-parity was not the goal — the graph is a *superset* of the old linear
  runner (adds a memory-ingestion node and per-node failure capture), so promotion
  + an end-to-end integration test replaced the originally-planned parity diff.
* Acceptance: one orchestrator remains; CI uses it; `tests/test_daily_graph_integration.py`
  drives all 17 nodes in order to a success run_status.

### P1-2. Checkpointing and conditional routing
* Output: SQLite-backed LangGraph checkpointer; explicit graph branches for
  memory-unavailable, empty-decision, all-trades-rejected, and execution-failure,
  each still exporting run status and diagnostics.
* Acceptance: killing the process mid-run and resuming completes the run without
  duplicate trades or journal entries.

### P1-3. Human-in-the-loop approval gate
* Output: LangGraph interrupt after risk review, before execution. CLI to
  approve/reject/edit pending trades; `AUTO_APPROVE=true` env flag for scheduled CI runs.
* Acceptance: with auto-approve off, the run pauses and persists across process
  restarts; approval resumes and executes; rejection journals a vetoed-run record.

### P1-4 ∥. Langfuse tracing and cost tracking
* Output: Langfuse tracing wired into the LLM gateway plus graph-node spans; run-level
  cost/latency summary in `run_status.json` and on the dashboard; durable run-history
  table (not just latest run).
* Acceptance: a full daily run appears as one trace tree with per-node cost; run
  history survives across runs.

## Phase 2 — Evals & Calibration (~2 weeks)

Goal: measure the AI, don't just run it.

### P2-1. Decision eval harness in CI
* Output: `evals/` with 6+ golden scenarios (fixture market context + portfolio
  state): bull market, crash, high cash, overconcentration, missing data, stale
  memory. Deterministic scorers (schema validity, risk compliance, citation
  validity) plus an LLM-as-judge grounding scorer. `make eval` target and a CI job
  gating prompt/schema changes. Track results across models and prompt versions.
* Acceptance: an intentionally broken prompt fails CI; eval results are persisted
  per run with model + prompt version.

### P2-2 ∥. Prediction calibration metrics
* Input: `data/predictions.jsonl` history.
* Output: Brier score, calibration curve data, and per-confidence-bucket hit rate,
  recomputed from history and rendered on the public dashboard. Expand prediction
  records with horizon, thesis, and benchmark-relative return.
* Acceptance: metrics recompute deterministically from historical data; dashboard
  page renders with real data.

### P2-3 ∥. Grounding check before journaling
* Output: an evaluator step that verifies decision claims against available market
  context, news, memory, and portfolio state; unsupported claims flagged and stored
  with the decision (and block tweeting).
* Acceptance: a fixture decision with a fabricated claim gets flagged; findings
  appear in the decision journal.

## Phase 3 — Multi-Agent & Tools (2–3 weeks)

Goal: real agent architecture with the debate transcript as a product feature.

### P3-1. Bull/bear/risk analyst debate
* Output: three analyst nodes (cheap model tier) producing structured theses; a PM
  synthesis node (strong tier) whose response schema requires an explicit
  `bear_case_response`; full debate transcript persisted in the decision journal and
  rendered on the dashboard.
* Acceptance: journal entries contain all four structured outputs; eval harness
  gains at least one debate scenario.

### P3-2 ∥. Typed tool calling for research
* Output: a tool registry with Pydantic input/output schemas — `get_price`,
  `get_history`, `search_news`, `retrieve_memory`, `get_portfolio` — and a
  tool-calling research agent that loops over them; every tool call recorded in the
  decision trace.
* Acceptance: decision journal shows the tool-call sequence; invalid tool arguments
  are rejected and retried.

### P3-3 ∥. Model routing
* Output: gateway routing — cheap tier for analysts/summaries/tweets, strong tier for
  the final decision; graceful fallback to a second provider on failure.
* Acceptance: a simulated provider outage falls back and the run completes; per-run
  cost drops vs. all-strong baseline (documented).

## Phase 4 — Knowledge Layer (~2 weeks)

Goal: RAG worth writing about, with measured retrieval quality.

### P4-1. Chunking and metadata-filtered retrieval
* Input: SEC ingestion (`scripts/ingest_sec_filings.py`, `src/memory/`).
* Output: recursive chunk splitting of filing sections; rich payload metadata
  (ticker, form type, item, filed date, sector); retrieval using metadata filters;
  retrieval eval set expanded to 20+ scenarios with before/after scores.
* Acceptance: retrieval eval score improves over the unchunked baseline and the
  delta is documented in the eval fixtures.

### P4-2 ∥. Additional knowledge sources
* Output: earnings-call transcript and 10-Q ingestion into the same memory schema,
  with source metadata and citations.
* Acceptance: retrieved earnings context appears (cited) in at least one golden-
  scenario eval.

### P4-3 ∥. Lessons-learned reflection agent
* Output: a weekly graph that reads closed predictions and trades, synthesizes
  `risk_lesson`/`mistake` memories with citations, and ingests them.
* Acceptance: lessons appear in the next daily run's retrieved memory context;
  re-running the same week is idempotent.

## Phase 5 — Surface & Reach (2–3 weeks)

Goal: make the system legible to outsiders.

### P5-1. MCP server for the fund
* Output: `mcp/` server exposing read-only tools: holdings, performance history,
  decision journal, debate transcripts, memory search.
* Acceptance: Claude Desktop/Code can answer "why did the fund sell NVDA in June?"
  against real data.

### P5-2 ∥. Risk Engine V2
* Output: repo-owned sector metadata file; sector-concentration limits; deterministic
  stop-loss (>15% drop) and take-profit (>40% gain) SELL proposals journaled as
  first-class risk events and routed through the normal risk/execution pipeline.
* Acceptance: unit tests per rule; system-generated SELLs appear in the journal with
  a `system` origin marker.

### P5-3 ∥. Weekly investor letter
* Output: AI-written weekly letter (performance, winners/losers, portfolio changes,
  outlook) generated through the gateway with grounding check, published to the
  dashboard; optional X thread mode, disabled by default.
* Acceptance: letter generation is idempotent per week; grounding check runs before
  publish.

### P5-4 (optional). Replay backtester
* Scope carefully — see `docs/ROADMAP.md` §7 (lookahead contamination). Build a
  *replay* harness for pipeline determinism and cached-decision regression testing,
  not a historical "would the LLM have won" backtest.

## Parked / Rejected

See `docs/ROADMAP.md` §7: live brokerage integration, decision-model fine-tuning,
knowledge graphs, market microstructure simulation, SaaS-ification, React SPA
dashboard, hand-rolled agent frameworks, naive historical backtesting.
