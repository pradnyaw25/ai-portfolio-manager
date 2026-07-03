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

### P1-3. Human-in-the-loop approval gate — DONE (in-process)
* Output: a `human_approval` graph node between rebalance and execution. With
  `AUTO_APPROVE=true` (default) it is a pass-through, so scheduled/CI runs are
  unattended. With it off, the node blocks and prompts the operator in-terminal to
  approve (execute all) / reject (veto all) / edit (execute a chosen subset); the
  decision is recorded in `run_status.human_review`.
* Note — deviation from the original spec: LangGraph's `interrupt()` requires a
  checkpointer, and every checkpointer serializes the whole graph state. Our
  `PortfolioRunState` carries live handles (engine, market/news clients, stores)
  that are not serializable, so durable cross-process pause/resume is not possible
  without a state refactor. Chose an in-process blocking gate instead (see follow-up).
* Follow-up (deferred): durable cross-process approval via a two-phase
  decide→persist→execute split, so a run can be approved after a restart.
* Acceptance (adjusted): auto-approve path is unattended; manual path prompts and
  gates execution; reject vetoes all trades; edit executes only the chosen subset;
  decision recorded in the run record. Covered by `tests/test_human_approval.py`.

### P1-4 ∥. Langfuse tracing and cost tracking — DONE
* Output: optional Langfuse tracing (`src/observability/tracing.py`) wired into the
  LLM gateway (a generation per call, with model/tokens/cost) and every graph node
  (a span each) under a per-run root span — a no-op unless `LANGFUSE_*` keys are set.
  Per-run LLM cost/latency (`src/llm/cost.py`) aggregated from the gateway call log —
  each call tagged with its `run_id` via a contextvar (`src/llm/context.py`) — and
  surfaced in `run_status.json` under `llm` and on the dashboard. Durable run history
  (`src/storage/run_history_store.py` → `data/run_history.jsonl`, exported to
  `public/run_history.json`), upserted by run_id.
* Acceptance: verified end-to-end — a run tags its LLM calls, aggregates cost into
  run_status, records durable history, and (with keys) emits one trace tree with
  per-node spans + per-call generations. Covered by `tests/test_llm_cost.py`,
  `tests/test_run_history_store.py`, `tests/test_tracing.py`, and gateway run_id tagging.

## Phase 2 — Evals & Calibration (~2 weeks)

Goal: measure the AI, don't just run it.

### P2-1. Decision eval harness in CI — DONE
* Output: `evals/` with 6 golden scenarios (bull market, crash, high cash,
  overconcentration, missing data, stale memory). Deterministic scorers
  (`evals/scorers.py`: schema validity, risk compliance, citation validity) plus an
  optional LLM-as-judge grounding scorer (`evals/grounding.py`). `evals/runner.py`
  runs the real agent, scores each decision, and persists a per-run summary with
  model + prompt version to `data/eval_results.jsonl`; exits non-zero if any
  scenario fails. `make eval` target (temperature 0) and `.github/workflows/evals.yml`
  gating PRs that touch prompts/schemas/agent.
* Note: the harness runs the live model in CI (deterministic scorers are the hard
  gate — robust to wording; grounding is a soft signal, non-gating on judge error).
  Everything is injectable, so `tests/test_evals.py` covers scorers + the full gate
  with a fake decide/judge and no API key.
* Acceptance: verified — a broken decision (off-universe trades, or decide raising)
  drives the runner to 0/6 and a non-zero exit; results persist with model +
  prompt version. Covered by `tests/test_evals.py` (16 tests).

### P2-2 ∥. Prediction calibration metrics — DONE
* Output: `src/scoring/calibration.py` computes Brier score, a bucketed calibration
  curve (predicted confidence vs. observed win rate), and per-bucket hit rate over
  resolved predictions — pure/deterministic. Wired into `predictions.json` via the
  exporter and rendered on `predictions.html` (Brier summary + calibration chart +
  bucket table; JSONL fallback mirrors the math in JS). Prediction records expanded
  with `horizon_days` + `thesis` (at creation) and benchmark-relative `alpha`
  (at scoring).
* Acceptance: metrics recompute deterministically (unit-tested against hand
  calculations); dashboard verified rendering both the empty state and a populated
  8-prediction calibration curve in a browser with no console errors. Covered by
  `tests/test_calibration.py`, `tests/test_prediction_records.py`, and the exporter
  test in `tests/test_reporting.py`.

### P2-3 ∥. Grounding check before journaling — DONE
* Output: `src/scoring/grounding.py` — an LLM-as-judge `check_grounding` that
  verifies decision claims against the run's market context, memory, and portfolio.
  Wired as a `check_grounding` graph node after `decide_trades`; findings stored on
  the decision journal entry (`grounding` field) and surfaced on `run_status`. A
  flagged decision **blocks tweeting** (`tweet_publish.status = "blocked_grounding"`).
  Degrades to `unavailable` (non-blocking) on judge failure. Shares the
  `GroundingVerdict` schema with the eval harness (deduped `evals/grounding.py`).
* Acceptance: verified end-to-end — a decision with a fabricated claim is flagged,
  the finding lands in the decision journal, and the tweet is blocked (service never
  called). Covered by `tests/test_grounding_check.py` (6 tests).

## Phase 3 — Multi-Agent & Tools (2–3 weeks)

Goal: real agent architecture with the debate transcript as a product feature.

### P3-1. Bull/bear/risk analyst debate — DONE
* Output: `src/agents/analysts.py` (Bull/Bear/Risk analysts, cheap tier, structured
  `AnalystThesis`) + `src/agents/debate.py` (`run_debate` orchestrates the three then
  the PM). The PM (strong tier) gains a required `bear_case_response` when given the
  debate. The transcript is embedded in the decision (`debate` key), so it persists in
  the decision journal and renders on `decisions.html` (bull/bear/risk with conviction
  + the PM's bear-case response). `decide_trades` now calls `run_debate`.
* Eval: added a `debate` golden scenario (`expects_debate`) routed through `run_debate`,
  plus a `score_debate_completeness` deterministic scorer (all three theses + a
  non-empty `bear_case_response`).
* Acceptance: verified — decision/journal carry all four structured outputs; dashboard
  renders the debate (checked in a browser, no console errors); eval harness has a
  debate scenario + scorer. Covered by `tests/test_debate.py` and `tests/test_evals.py`.
* Note: adds 3 analyst LLM calls (cheap tier) per run ahead of the PM synthesis.

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
