# AI Portfolio Manager Roadmap

Each task is scoped so an independent coding agent can execute it: inputs, outputs,
and acceptance criteria are explicit. Rationale and prioritization live in
`docs/ROADMAP-V2.md` (current) and `docs/ROADMAP.md` (v1, all executed).

Tasks assume the `.venv` environment and `make test` green before/after.

**Status:** Phases 0–5 (v1) are all DONE (archived below). The current plan is the
**V2** block: the v1 roadmap built the machinery; V2 proves it works, makes it legible,
and turns it into a platform.

---

# V2 — Evidence, Distribution & Platform (current plan)

Ordered by ROI. `∥` = parallelizable. See `docs/ROADMAP-V2.md` §2/§6 for the why.

## V2 · Next 30 days (highest ROI)

### V1-1. Baseline + ablation harness
* Input: the daily cycle + stores; a config knob for fund variants (fund-as-config).
* Output: a runner that executes, over the same days, the live fund plus baselines
  (buy-and-hold SPY, random-from-watchlist) and ablated variants (no-memory,
  no-debate, no-tools). Metrics per variant (return, alpha, Brier once resolved,
  decision-quality proxy). Results persisted and rendered on the dashboard.
* Acceptance: a single command produces a comparison table across ≥4 variants; the
  dashboard shows fund-vs-SPY-vs-random; the numbers are reproducible.

### V1-2 ∥. Strong-tier PM model + measured delta — DONE
* Output: PM/judges on a frontier model (analysts stay cheap), selected by measuring
  eval-pass rate and a decision-quality delta vs the cost increase (using the existing
  cost log). Decision documented.
* Acceptance: `make eval` shows the delta; the model choice is justified by data, not
  vibes; defaults remain cost-safe.
* Done: `make eval-compare` (`scripts/compare_strong_model.py`) runs the eval set under
  each candidate strong model with a fixed LLM judge (`src/scoring/decision_quality.py`)
  and reports pass-rate + rubric quality + cost/latency. Measured curve
  (`docs/model-selection.md`): flagships `gpt-4o`/`gpt-4.1` cost ~11x for no reliable
  quality gain; `gpt-4.1-mini` is the sweet spot. Default strong tier promoted
  `gpt-4o-mini` -> `gpt-4.1-mini` (cheap stays `gpt-4o-mini`); cost-safe (<$0.001/decision).

### V1-3 ∥. Presentation pass
* Output: README hero image + 3-line pitch + 90s demo GIF + MCP clip; landing page
  self-explains (what/why/how) and links GitHub + X; the empty calibration module is
  hidden until predictions resolve.
* Acceptance: a cold visitor understands the project in <10s; GitHub reachable from the
  site; no "Loading…"/empty-metric first impression.

### V1-4 ∥. Real-query retrieval eval
* Output: 25–30 hand-labeled queries against the live Qdrant corpus with real
  embeddings; recall/precision/MRR reported alongside (not replacing) the synthetic
  chunking eval, with the honesty caveat documented.
* Acceptance: a keyed `make retrieval-eval` reports real-corpus numbers; the synthetic
  eval is explicitly labeled as mechanism-demonstration.

### V1-5. Debate that earns its keep
* Output: information asymmetry per analyst (bear ← risk-factor filings, bull ←
  momentum/news, risk ← exposures) + one rebuttal turn (bear sees bull) + a
  disagreement/conviction-spread metric recorded per debate.
* Acceptance: convictions no longer cluster; the debate feeds a measurable variant in
  V1-1 (debate vs no-debate); a real transcript shows genuine disagreement.

## V2 · Next 90 days (depth)

### V1-6. Replay harness
* Output: record each run's exact inputs (prices, news, memory snapshot) to a replay
  store; deterministic re-execution; prompt/schema-change regression on frozen days in
  CI. (Promotes + reframes v1 P5-4.)
* Acceptance: replaying a past run reproduces its decision byte-for-byte from cached
  inputs; a prompt change that alters a frozen-day decision is caught in CI.

### V1-7 ∥. SQLite/DuckDB system of record
* Output: migrate trades/decisions/predictions off CSV/JSONL into a real DB with
  transactional upserts; decouple Pages exports; stop committing `data/` to `main`
  (branch/artifacts).
* Acceptance: no daily-data commits on `main`; the ledger is queryable; existing
  idempotency guarantees preserved.

### V1-8 ∥. Second real provider (Anthropic) + routing experiment
* Output: an Anthropic provider behind the existing seam; a cross-provider eval
  comparison; make "routing" actually route.
* Acceptance: a run can be served by either provider; an eval compares them; fallback
  crosses providers.

### V1-9. Durable two-phase HITL
* Output: decide→persist→approve→execute split so a run can be approved after a
  restart or from the dashboard. (Closes the honest P1-3 deferral.)
* Acceptance: kill the process mid-approval, resume, approve, execute — no duplicates.

### V1-10. Intraday event reactor
* Output: price-move triggers evaluated by a cheap agent restricted to *proposing risk
  exits* (bounded authority); routed through the same risk/execution guardrails.
* Acceptance: a simulated intraday drop proposes a stop-loss exit that flows through
  the normal pipeline; the reactor cannot open new positions.

### V1-11 ∥. Memory impact instrumentation
* Output: correlate cited memories with won/lost predictions; a decay/consolidation
  policy for the memory store.
* Acceptance: a report shows which memory types/citations precede better outcomes;
  stale low-value memories are decayed.

## V2 · Next 6–12 months (standout)

### V1-12. Multi-fund tournament (flagship)
* Output: N fund configs (model × memory × debate × risk) running in public with a
  league table on the dashboard; the tournament reuses the V1-1 fund-as-config seam.
* Acceptance: ≥3 funds run concurrently on shared data; a public league table ranks
  them; weekly content is generated from the standings.

### V1-13 ∥. Extract `decision-audit` OSS package
* Output: the grounding gate + citations + decision journal as a standalone pip
  package; this repo becomes its reference deployment.
* Acceptance: `pip install` + a minimal example works outside this repo; docs + CI +
  license.

### V1-14 ∥. Calibration-aware position sizing
* Output: size positions by a Kelly fraction scaled by the fund's *measured* confidence
  reliability (from its own calibration data).
* Acceptance: sizing provably responds to calibration; unit-tested against the
  deterministic risk layer.

### V1-15. Streaming data plane + budgeted intraday agents
* Output: event-log-backed streaming inputs; intraday agents under explicit token/
  latency budgets.
* Acceptance: bounded, backpressure-aware intraday operation within budget.

---

# Archive — v1 (all DONE)

Delivered by the v1 roadmap (`docs/ROADMAP.md`); kept for provenance.

## Phase 0 — Harden the Foundation (~1 week)

Goal: kill the fragility before building on it. Everything later flows through P0-1.

### P0-1. Create the LLM gateway — DONE
* Input: the three existing LLM call sites (`src/agents/portfolio_manager.py`,
  `src/agents/rebalance_checker.py`, `src/agents/tweet_generator.py`).
* Output: `src/llm/gateway.py` (surfaced via `src/llm/__init__.py` as
  `complete_structured` / `complete_text` / `complete_with_tools`): Pydantic
  validation of every response with a repair-retry, exponential backoff on transient
  errors, per-tier model/provider/temperature from config, and a per-call cost/latency
  log. Every agent flows through it; the later provider seam (P3-3) and tool loop
  (P3-2) were built on this foundation.
* Acceptance: verified — no raw `json.loads` on LLM output in `src/` (remaining
  `json.loads` are file/JSONL reads and tool-arg parsing inside the gateway layer);
  repair path and backoff covered by `tests/test_llm_gateway.py`.

### P0-2 ∥. Config consolidation and dead-code removal — DONE
* Output:
  * Model names/tiers, temperature, watchlist, and Qdrant collection name in typed
    config (`src/config.py`), validated by `validate_config()` which lists all
    problems at once. Watchlist moved to `config/watchlist.yaml` (loaded/normalized
    by `_load_watchlist`), shared by `src/research/market_context.py` and
    `scripts/ingest_sec_filings.py`. `validate_config()` is called at the top of the
    daily cycle (`run_daily_cycle_graph`) and the eval harness entrypoint
    (`evals/runner.py:main`), so both fail loudly before any API spend.
  * Deleted `src/agents/researcher.py` and the unused config keys
    (`ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `MAX_POSITIONS`) — none remain in
    `src/` or `scripts/`.
  * Removed unused deps (`plotly`, `anthropic`).
* Note on acceptance: the original `grep -r "gpt-4o-mini" src/` == empty criterion is
  intentionally *not* met by two legitimate references — the `_MODEL_PRICING` table
  key in `gateway.py` (a pricing lookup must key by model name) and the config
  defaults in `config.py` (P3-3 deliberately kept `gpt-4o-mini` as the default so
  scheduled-run cost doesn't change silently). The criterion's intent — no hardcoded
  model *selection* in agent code — is satisfied: every agent resolves its model
  through config tiers.
* Acceptance: verified — no dead keys or `researcher.py`; startup validation fails
  loudly on invalid config (covered by `tests/test_config.py`); tests green.

### P0-3 ∥. Idempotent stores — DONE
* Input: `src/storage/` (trades CSV, decisions JSONL, predictions JSONL).
* Output: upsert keyed by run_id instead of blind append, following the existing
  `run_history_store.record()` pattern (load → filter matching key → rewrite):
  * `TradeStore.save_run(run_id, trades)` — batch upsert replacing all rows for the
    run. Keyed on the *run as a whole*, not (run_id, symbol, action): a single run
    can legitimately hold two same-symbol/action trades (a PM buy + a rebalance
    top-up), which a natural per-row key would collapse. `execute_trades` in
    `main.py` now calls it once per run (empty batch clears prior rows).
  * `DecisionStore.save(...)` upserts the single journal row by run_id.
  * `PredictionStore.save(...)` upserts by (run_id, symbol); prediction IDs are now
    deterministic (`uuid5(namespace, "{run_id}:{symbol}")`) so a re-run recreates an
    identical row rather than a new random id. Legacy rows without a run_id still
    append.
* Note: kept the CSV/JSONL formats (the SQLite migration in `docs/ROADMAP.md` §3 is a
  separate, larger bet); P0-3's scope is upsert semantics on the current stores.
* Acceptance: verified — re-running a run_id yields byte-identical files with no
  duplicates, other runs are preserved, and the same-symbol collision case keeps both
  trades. Covered by `tests/test_store_idempotency.py` (8 tests).

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

### P1-2. Checkpointing and conditional routing — DONE
* Output (shipped as two PRs):
  * **PR 1/2 — conditional routing.** A semantic branch after `check_rebalance`: with
    no approved trades (empty decision or all rejected), skip
    human_approval/execute/track and route straight to `journal_run`, still exporting
    run status. Branch conditions (empty decision, no approved trades, memory
    unavailable, execution failure) recorded on `run_state.diagnostics` →
    `run_status["diagnostics"]`.
  * **PR 2/2 — durable resume.** Since the graph state carries non-serializable live
    handles (the P1-3 blocker), LangGraph's native checkpointer isn't usable; instead a
    SQLite `RunProgressStore` persists per-run phase completion. `run_daily_cycle_graph
    (resume=True)` (and `scripts/daily_run.py --resume`) re-enters the most recent
    unfinished run **reusing its run_id**, so the P0-3 idempotent stores dedupe
    re-executed writes. The one non-idempotent external side effect (tweet publish) is
    skipped on resume if already completed.
* Note: chose idempotency-based resume over the large state-refactor needed for
  LangGraph's native `SqliteSaver` (documented tradeoff; the durable store is still
  SQLite-backed).
* Acceptance: verified — resume reuses the unfinished run_id and completes, marking it
  done; an already-published tweet is not re-posted; the router skips execution on no
  approved trades but still journals + exports. Covered by `tests/test_run_progress.py`
  (6) and `tests/test_daily_graph_routing.py` (4).

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

### P3-2 ∥. Typed tool calling for research — DONE
* Output: a tool registry (`src/llm/tools.py`) with Pydantic input schemas that
  validates model args (invalid → structured error the model corrects); five tools
  (`get_price`, `get_history`, `search_news`, `retrieve_memory`, `get_portfolio`) in
  `src/agents/research_agent.py`; a gateway tool-calling loop
  (`complete_with_tools`, capped at `max_rounds`) built on the P3-3 provider seam.
  A `research_followup` graph node (augments — keeps `MarketContextBuilder`) runs the
  agent before `decide_trades`; the brief is merged into the context and the brief +
  tool-call trace are stored on the decision journal (`research_brief`) and rendered
  on `decisions.html`. Runs on the cheap tier.
* Note (design Q1): augment, not replace — the deterministic base context is
  unchanged. Eval scorer for the research node deferred (the eval harness only
  exercises the decide path, not the graph node).
* Acceptance: verified end-to-end — the agent makes tool calls (loop tested,
  `max_rounds` enforced), the tool-call sequence lands in the decision journal, and
  invalid tool arguments return a structured error for the model to retry. Dashboard
  renders the research trace (browser-checked, no console errors). Covered by
  `tests/test_tool_calling.py`.

### P3-3 ∥. Model routing — DONE
* Output: provider abstraction (`src/llm/providers/` — `LLMProvider`,
  `ProviderResponse`, `OpenAIProvider`) behind the gateway; per-tier routing
  (`src/llm/routing.py`) resolving `(provider, model)` for cheap/strong from config;
  optional fallback route tried after the primary exhausts retries. Cost log records
  the serving `provider` and `fell_back`. Design: `docs/design-phase3.md`.
* Note: OpenAI-only for now (Q2a) — fallback is a second OpenAI model; the interface
  is provider-agnostic so Anthropic/Ollama are a ~1-file add later. Defaults keep both
  tiers on `gpt-4o-mini` (no silent cost change); the cost-drop is opt-in by setting
  `LLM_STRONG_MODEL` to a pricier model (documented in README + `.env.example`).
* Acceptance: verified — a simulated primary-provider outage falls back to the
  secondary and the call completes (`fell_back=true` logged); config validates
  per-tier providers + partial fallback. Covered by `tests/test_routing_fallback.py`
  and `tests/test_config.py`. Existing gateway tests pass unchanged.

## Phase 4 — Knowledge Layer (~2 weeks)

Goal: RAG worth writing about, with measured retrieval quality.

### P4-1. Chunking and metadata-filtered retrieval — DONE
* Input: SEC ingestion (`scripts/ingest_sec_filings.py`, `src/memory/`).
* Output (shipped as two PRs):
  * **PR 1/2 — ingestion.** `src/memory/chunking.py` (`RecursiveCharacterTextSplitter`,
    ~1k-char overlapping chunks, capped + logged). `filing_sections_to_memory_records`
    emits one record/vector per chunk with a deterministic id
    (`10k:{ticker}:{accession}:{item}:{NNNN}`) and payload metadata (item, form,
    filing date, `chunk_index`, `total_chunks`, `sector`). Sector comes from a
    repo-owned `config/sectors.yaml` via `config.sector_for()`. 12k truncation lifted
    to a `SECTION_MAX_CHARS` pre-chunk cap.
  * **PR 2/2 — retrieval + eval.** `build_qdrant_filter` pushes symbol/type/sector
    constraints into Qdrant (langchain-nested payload keys) instead of Python
    post-filtering; `_filter_memories` retained as a deterministic guard.
    `FundMemoryRetriever` accepts an injected store. A deterministic offline eval
    (`src/memory/retrieval_eval.py` + `src/memory/embeddings.py` hashing embedder +
    in-memory Qdrant) compares chunked vs unchunked over 20 scenarios; `make
    chunking-eval` runs it and gates on improvement.
* Acceptance: verified — over 20 scenarios chunking lifts hit@1 0.15→1.00, MRR
  0.26→1.00, recall@5 0.45→1.00; before/after committed at
  `tests/fixtures/memory_evals/chunking_baseline.json`. Covered by
  `tests/test_chunking.py`, `tests/test_embeddings.py`, `tests/test_retrieval_filters.py`,
  `tests/test_retrieval_eval.py`, and expanded `test_sec_filings.py`/`test_config.py`.

### P4-2 ∥. Additional knowledge sources — DONE
* Output: two new EDGAR sources ingested through the same chunking/sector pipeline
  as 10-K (P4-1):
  * **10-Q** — generalized EDGAR client (`get_latest_10q`, `extract_10q_sections`)
    and form-aware `filing_sections_to_memory_records` (Part I MD&A → thesis, market
    risk → risk_lesson; `10q:…` ids, `source_type=sec_10q`).
  * **8-K earnings** — `get_latest_earnings_8k` (filters to Item 2.02),
    `find_earnings_exhibit` / `fetch_earnings_release_html` (locates the EX-99
    exhibit via the accession index), and `earnings_release_to_memory_records`
    (`earnings_event` type, `earnings_event:…` ids, `source_type=earnings_8k`).
  * Citations: `10k:`/`10q:` added to `MEMORY_ID_PREFIXES` (earnings already citable),
    so filing/earnings memories can be attributed in the decision journal.
    `earnings_event` surfaced in the grouped retriever's `symbol_theses` group.
  * Chose real EDGAR 8-K press-release exhibits over a paid transcript feed.
* Acceptance: verified — an `earnings_and_10q_context` memory-retrieval scenario
  surfaces the 8-K earnings release and 10-Q MD&A (grouped, recall 1.0), and an
  `earnings_context` golden decision scenario carries a citable earnings memory that
  `score_citation_validity` accepts (and flags when the id is fabricated). Covered by
  `tests/test_knowledge_sources.py` (11 tests) + expanded `test_memory_evals.py`.

### P4-3 ∥. Lessons-learned reflection agent — DONE
* Output: a weekly LangGraph (`src/workflows/weekly_reflection_graph.py`:
  gather → reflect → ingest, with a conditional skip when the week is empty) over a
  `ReflectionAgent` (`src/agents/reflection.py`, strong tier, `ReflectionResponse`
  schema). `gather_week` selects the 7-day window's *scored* predictions (win/loss vs
  SPY) and executed trades; the agent distills `risk_lesson`/`mistake` lessons, each
  carrying the source prediction/trade ids (`cited_ids`) as provenance in metadata.
  Lesson memory ids are deterministic per `(week, index)` so re-ingestion upserts the
  same points. `scripts/weekly_reflection.py` + a `Weekly Reflection` GitHub Action
  (weekly cron) + `make reflect`. All deps (agent, stores, memory store) injectable.
* Acceptance: verified — (1) an ingested `risk_lesson`/`mistake` lesson surfaces in the
  daily `risk_lessons` retrieval group (end-to-end test against an in-memory Qdrant);
  (2) re-running the same week yields identical point ids (idempotent, no duplicates).
  Covered by `tests/test_reflection.py` (6 tests).

## Phase 5 — Surface & Reach (2–3 weeks)

Goal: make the system legible to outsiders.

### P5-1. MCP server for the fund — DONE
* Output: a read-only FastMCP server (`mcp_server/`, `make mcp`) with 7 tools —
  `get_holdings`, `get_performance_history`, `list_trades`, `list_decisions`,
  `get_decision`, `get_debate`, `search_memory` — over the existing stores. Query
  logic lives in `mcp_server/fund_data.py` (plain, injectable, no `mcp` import so it's
  unit-testable); `mcp_server/server.py` wires them into FastMCP. Named `mcp_server`
  (not `mcp`) to avoid shadowing the SDK; `pip install -e .` package discovery made
  explicit. `mcp` added to deps; client config snippet in `mcp_server/README.md`.
* Note: no tool can mutate state (read-only by construction). `search_memory` degrades
  to `unavailable` when Qdrant/embeddings are offline.
* Acceptance: verified — the tool chain answers "why did the fund sell NVDA?": a real
  `list_trades(symbol="NVDA", action="SELL")` finds the trade, and `get_decision` /
  `get_debate` return that run's reasoning. Covered by `tests/test_mcp_fund_data.py`
  (9 tests) with fake stores.

### P5-2 ∥. Risk Engine V2 — DONE
* Output:
  * **Sector-concentration limits** — `RiskManagerAgent.review` caps BUYs so no GICS
    sector (`config/sectors.yaml`, from P4-1) exceeds `MAX_SECTOR_CONCENTRATION`
    (default 40%); a breaching BUY is trimmed to the remaining budget or rejected.
    Running exposure accumulates across BUYs and is reduced by SELLs. Applies wherever
    `review` runs (main risk review + rebalance).
  * **Stop-loss / take-profit** — `src/agents/risk_events.py:generate_risk_events`
    scans marked-to-market positions and emits full-exit **system** SELLs for any
    position past `STOP_LOSS_PCT` (15% drop) or `TAKE_PROFIT_PCT` (40% gain) from cost
    basis. `main.review_risk` generates them from the snapshot, drops any LLM trade for
    the same symbol (system exit wins), and routes them through the same
    guardrails/execution. `TradePrediction.origin` (`"llm"`/`"system"`) tags them; the
    generated events are stored on `RiskReview.risk_events` and journaled under a new
    `risk_events` field on the decision.
  * Config knobs validated at startup; documented in README + `.env.example`.
* Acceptance: verified — unit tests per rule (stop-loss, take-profit, boundary,
  sector cap/accumulate/reject, SELL exempt) and pipeline integration (system exit
  supersedes the LLM trade; journal records the event with `origin="system"`).
  Covered by `tests/test_risk_engine_v2.py` (11 tests).

### P5-3 ∥. Weekly investor letter — DONE
* Output: `src/agents/investor_letter.py` — `gather_letter_facts` computes the week's
  facts deterministically (portfolio return vs SPY from `portfolio_history.csv` /
  `benchmark_history.csv`, winners/losers by position return, in-window trades);
  `InvestorLetterAgent` (strong tier, `InvestorLetterResponse` schema) writes a letter
  grounded in exactly those facts. `generate_weekly_letter` runs the shared
  `check_grounding` **before publish** — a flagged letter is blocked and nothing is
  written; a grounded letter is recorded (`InvestorLetterStore`, upsert by `week_end`)
  and exported to `public/investor_letter.{json,md}`. Optional X-thread posting behind
  `POST_INVESTOR_LETTER` (default off) via the existing `TwitterPublisher`.
  `scripts/weekly_letter.py` + a `Weekly Investor Letter` GitHub Action + `make letter`.
* Acceptance: verified — grounded → published + exported + one store row; flagged →
  `blocked_grounding` with nothing published; re-running a week upserts (one row,
  idempotent); X thread off by default, on when enabled. Covered by
  `tests/test_investor_letter.py` (8 tests).
* Follow-up (not in scope): a dedicated `investor_letter.html` dashboard page (the
  JSON/markdown are published; no HTML view yet).

### P5-4 (optional). Replay backtester
* Scope carefully — see `docs/ROADMAP.md` §7 (lookahead contamination). Build a
  *replay* harness for pipeline determinism and cached-decision regression testing,
  not a historical "would the LLM have won" backtest.

## Parked / Rejected

See `docs/ROADMAP.md` §7: live brokerage integration, decision-model fine-tuning,
knowledge graphs, market microstructure simulation, SaaS-ification, React SPA
dashboard, hand-rolled agent frameworks, naive historical backtesting.
