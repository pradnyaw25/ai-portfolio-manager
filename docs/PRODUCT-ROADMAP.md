# Glasshouse Fund — Weekend Product Roadmap

This is the execution layer for [`ROADMAP-V2.md`](ROADMAP-V2.md). The strategic
roadmap explains *why* the project should evolve; this document says what to pick up
on a weekend, where to start, and how to know the work is done.

The goal is not to maximize feature count or short-term paper returns. The goal is to
make Glasshouse Fund a technically credible, engaging, public laboratory for
controlled and auditable agent experiments.

## How to use this document

- Assume one weekend is **6–10 focused hours**.
- Keep at most two tasks in **Now**. A task belongs there only when its acceptance
  criteria and starting points are concrete.
- Move a task to **Done** only after its verification steps pass and the README is
  updated when the public behavior, pipeline, configuration, or structure changed.
- Record surprises, compromises, and deferred work in the task before stopping.
- Link the issue and PR/commit when they exist.
- Split work that no longer fits in one weekend rather than carrying a vague task.

Status values: `Ready`, `In progress`, `Blocked`, `Done`.

## Next session

**Recommended task:** W01 — Public data contracts and risk posture
**Last completed:** Roadmap created
**Known blockers:** None
**Start here:** Compare the fields used by `public/index.html` with the artifacts
written by `src/reporting/public_exporter.py`, especially `public/run_status.json`.

Before stopping a work session:

- [ ] Update the task status and check completed acceptance criteria.
- [ ] Record commands run, test results, and unexpected findings.
- [ ] Add issue and PR/commit links.
- [ ] Update the recommended next task above.
- [ ] Update `README.md` when required by the repository guidelines.

## Now

### W01 — Public data contracts and risk posture

**Status:** Ready
**Effort:** 6–8 hours
**Why:** The live landing page can show missing performance values while the dashboard
has the data. The dashboard also needs to explain holdings above documented position
limits instead of making the risk engine appear inconsistent.

#### Scope

- Define and validate the schema for every JSON artifact consumed by a public page.
- Make public exports atomic so a partial run cannot publish an incomplete artifact.
- Fix the homepage mapping for fund, SPY, QQQ, and alpha returns.
- Give stale, missing, or unavailable data an explicit visible state.
- Add a risk-posture view showing configured limits, current exposure, breaches,
  whether further buying is blocked, and whether drift caused the breach.

#### Acceptance criteria

- [ ] The homepage shows fund, SPY, QQQ, and alpha returns from one canonical export.
- [ ] CI validates every public JSON artifact against a typed contract.
- [ ] Missing or stale fields show an explicit state instead of an unexplained dash.
- [ ] Holdings above a configured limit are surfaced and explained.
- [ ] Export contract and UI behavior have automated tests.
- [ ] README public-dashboard documentation is current.

#### Starting points

- `public/index.html`
- `public/dashboard.html`
- `public/run_status.json`
- `src/reporting/public_exporter.py`
- `.github/workflows/daily-run.yml`

#### Verification

```bash
.venv/bin/python -m pytest
make dashboard
```

#### Notes / decisions

- Confirm whether the 10% position limit applies only at purchase time or also
  requires subsequent rebalancing. Make that policy explicit in code and UI.

### W02 — Safe, varied social publishing

**Status:** Ready
**Effort:** 6–10 hours
**Why:** X publishing already works, but repeated symbol theses, generic language,
truncated hashtags, and fail-open grounding make the feed less credible than the
underlying system.

#### Scope

- Add deterministic length budgeting before generation and validation after it.
- Deduplicate posts by symbol, thesis, and content type with configurable cooldowns.
- Rank candidate posts by novelty and importance; skip when nothing qualifies.
- Make public content quarantine rather than publish when grounding is unavailable.
- Add idempotency and retry behavior for temporary X failures.
- Record enough structured metadata to evaluate content formats later.

#### Acceptance criteria

- [ ] No published text contains a truncated word, URL, or hashtag.
- [ ] The same symbol/thesis cannot be selected repeatedly inside its cooldown.
- [ ] A routine no-trade run may intentionally produce no post.
- [ ] Unavailable grounding produces a quarantined artifact, not a published claim.
- [ ] Temporary failures retry safely without duplicate posts.
- [ ] Unit tests cover selection, deduplication, length, grounding, and idempotency.
- [ ] [`CONTENT-STRATEGY.md`](CONTENT-STRATEGY.md) matches the implementation.

#### Starting points

- `src/agents/tweet_generator.py`
- `src/social/twitter.py`
- `scripts/weekly_state_tweet.py`
- `prompts/tweet_writer.txt`
- `prompts/state_tweet.txt`
- `.github/workflows/daily-run.yml`

#### Verification

```bash
.venv/bin/python -m pytest tests/test_tweet_generator.py tests/test_twitter_publisher.py tests/test_tweet_media.py
```

## Next

### W03 — Keyless frozen-run demo

**Status:** Ready
**Effort:** 6–8 hours
**Outcome:** `make demo` replays a committed canned day without credentials and walks
through research, memory, debate, risk, execution, prediction, and journal output.

Acceptance criteria:

- [ ] Works from a clean clone without network access or API keys.
- [ ] Produces stable, inspectable demo artifacts outside tracked production data.
- [ ] README explains the command above the full setup instructions.
- [ ] A 60–90 second dashboard demo and a short MCP interrogation clip are recorded.

### W04 — Real-corpus retrieval evaluation

**Status:** Ready
**Effort:** 8–12 hours
**Outcome:** A versioned set of at least 30 human-written questions against actual SEC
filings measures retrieval rather than only demonstrating that synthetic chunking
scenarios work.

Acceptance criteria:

- [ ] Each query labels expected ticker, form, section, and relevant passage(s).
- [ ] Evaluation reports hit@1, hit@5, MRR, citation validity, and answer grounding.
- [ ] Whole-section, dense chunked, filtered, and at least one hybrid/reranked variant
  are compared on identical queries.
- [ ] Results, corpus version, embedding model, and limitations are reproducible.
- [ ] A concise result appears on the engineering page.

### W05–W07 — Point-in-time run bundles and deterministic replay

**Status:** Ready
**Effort:** 24–30 hours over three weekends
**Outcome:** Every run can be reconstructed from immutable inputs and compared under a
different prompt, model, memory, debate, or tool configuration without looking into
the future.

Milestones:

1. Specify and persist a versioned run bundle: portfolio, timestamps, prices, history,
   news, filings/memories, prompt versions, model metadata, configuration, and raw
   responses.
2. Implement `make replay RUN_ID=...` with network and execution disabled.
3. Implement `make replay-compare RUN_ID=...` and emit structured decision, risk,
   cost, and latency diffs.

Acceptance criteria:

- [ ] Replay performs no market-data, news, embedding, model, X, or trade side effect.
- [ ] Identical inputs and configuration produce an equivalent normalized result.
- [ ] Missing bundle fields fail with an actionable compatibility message.
- [ ] CI replays at least one frozen run.
- [ ] README and architecture documentation describe the mechanism and limitations.

### W08–W09 — SQLite/DuckDB system of record

**Status:** Ready
**Effort:** 14–20 hours over two weekends
**Outcome:** Operational data is queryable and transactional; CSV, JSON, and JSONL
become generated exports rather than the primary ledger.

Acceptance criteria:

- [ ] Runs, events, decisions, retrievals, model calls, trades, predictions, and
  publication attempts have stable relational identities.
- [ ] Writes are transactional and idempotent by run/event identity.
- [ ] Existing data can be migrated and validated without loss.
- [ ] Public exports are generated from the database.
- [ ] Daily automation no longer pollutes main with routine data commits, or the
  chosen publishing branch/storage design is explicitly documented.

### W10 — Independent model provider experiment

**Status:** Ready
**Effort:** 8–12 hours
**Outcome:** The existing gateway performs a genuine cross-provider replay comparison
of quality, grounding, schema reliability, cost, latency, and decision stability.

### W11 — Memory impact instrumentation

**Status:** Ready
**Effort:** 8–12 hours
**Outcome:** The system can answer which memories were retrieved, cited, influential,
superseded, and associated with later prediction outcomes.

### W12 — Experiments dashboard

**Status:** Ready
**Effort:** 6–10 hours
**Outcome:** Visitors can inspect replay diffs, real retrieval quality, model
quality-versus-cost, debate disagreement, memory use, and calibration by cohort.

## Later

### W13–W16 — Multi-fund tournament MVP

Run at least three configurations from identical point-in-time inputs and give each
the same starting capital, timing, execution rules, and deterministic risk contract.
Publish a league table covering return versus SPY, drawdown, turnover, prediction
accuracy, Brier score, cost, risk interventions, and citation quality.

This begins only after replay and the system of record are reliable. The intended
funds are:

1. Full system: memory, debate, tool research, strong PM.
2. Minimal system: single PM without memory or debate.
3. A clearly documented contrarian or risk-first configuration.

### Decision-audit OSS extraction

Extract the reusable grounding, citation, audit-journal, and publication-gate pieces
only after replay reveals a stable interface. The fund should remain the reference
deployment and integration test.

### Event-driven risk reactor

Add intraday events only after durable events and replay exist. Initially restrict
the model to proposing risk exits; deterministic rules and an optional human gate
retain execution authority.

## Done

Move completed task summaries here with completion date and PR/commit links. Keep the
full acceptance criteria in history rather than duplicating them indefinitely.

## Deferred deliberately

- Live brokerage integration
- Fine-tuning before a measured dataset and failure taxonomy exist
- Knowledge graph work without evidence that vector/relational retrieval is limiting
- A frontend rewrite solely to change frameworks
- More analyst personas without an ablation showing a new information source helps
- Unbounded intraday autonomous trading
- Optimizing short-term returns at the expense of experimental validity
