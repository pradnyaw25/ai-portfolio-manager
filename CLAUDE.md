# CLAUDE.md

## Project Overview

AI Portfolio Manager — an LLM-powered paper trading system that runs a daily cycle:
**Research → Decision → Risk Check → Rebalance Check → Execute → Journal → Report**

The system uses LLM agents to analyze markets, make trade decisions, and manage a simulated $1M portfolio. It enforces risk guardrails deterministically (position sizing, turnover limits, confidence thresholds) and requires the AI to justify holding excess cash.

## Architecture

- `src/main.py` — Orchestrates the daily cycle
- `src/workflows/daily_graph.py` — the LangGraph cycle (22 guarded nodes) that actually runs
- `src/research/market_context.py` — Deterministic prices, returns and news for holdings + watchlist
  (there is no `researcher.py`; the old ResearchAgent was replaced by MarketContextBuilder)
- `src/agents/` — LLM-powered agents:
  - `analysts.py` / `debate.py` — bull, bear and risk cases plus the bear's rebuttal
  - `research_agent.py` — tool-calling follow-up research
  - `portfolio_manager.py` — LLM decides trades (BUY/SELL/HOLD) with cash allocation rules
  - `risk_manager.py` — Deterministic guardrails: validates, filters, caps trades
  - `rebalance_checker.py` — Enforces cash target (≤25%): deploy capital or write a cash thesis
  - `tweet_generator.py` — Generates social media content from results
- `src/simulator/` — Portfolio engine (execution) and performance tracking
- `src/storage/` — Persistence: portfolio state (JSON), trades (CSV), decisions (JSONL)
- `src/data_sources/` — Market data, news, and benchmark API clients
- `src/models/` — Dataclasses: Position, PortfolioSnapshot, TradePrediction, Trade
- `src/config.py` — All tunables via env vars (capital, position size, turnover, cash target)

## Key Rules

- **Cash target**: If cash > 25%, the system must deploy or justify (see `rebalance_checker.py`)
- **Max position size**: 10% of portfolio per holding
- **Max daily turnover**: 20% of portfolio value
- **Min trade confidence**: 0.60 to pass risk review
- **Rebalance trades go through the same RiskManagerAgent** — no bypassing guardrails

## Working on This Repo

- Use the `.venv` virtual environment: `.venv/bin/python`
- Config is in `src/config.py`, all values overridable via `.env`
- `data/` and `reports/` ARE committed, not gitignored — the daily run does
  `git add -f public data reports`, so the published site and the data behind it move together.
  14 files under `data/` and 35 under `reports/` are tracked. Don't "fix" this by ignoring them.
  Do avoid staging them by hand: `pytest` writes to `data/llm_calls.jsonl`,
  `data/social_posts.jsonl` and `public/baseline_comparison.json`, so a local test run leaves
  them dirty and they should be discarded rather than committed
- The decision journal (`data/decisions.jsonl`) is the audit trail — always include `cash_thesis` and `rebalance_trades` when saving

## README Maintenance

**Always keep `README.md` up to date** when adding features, changing the pipeline, or modifying the project structure. The README is the public face of this project. If you add a new agent, config option, or pipeline step, update the README to reflect it.

## Future Tasks

> Reconciled against the code on 2026-07-07; SEO section + prediction/letter status re-reconciled
> 2026-07-17; **prediction counts re-reconciled against `data/predictions.jsonl` on 2026-08-07**
> (the launch gate is cleared — see "Recently Completed" under Distribution & SEO). Completed items
> moved to "Recently Completed" below rather than deleted, so the backlog keeps its history.

### High Priority
- [ ] **Correlation-aware diversification** — Sector concentration *is* enforced
  (`risk_manager.py:98-132`, 40% cap). Correlation is not: there is no correlation code anywhere
  in `src/`. Two names in different GICS sectors that move together still pass every check.
- [ ] **Unit-test the rebalance checker** *(started 2026-07-09)* — `tests/test_rebalance_checker.py`
  now exists (added with the same-day-rebuy fix, #74) and covers the just-sold exclusion + prompt,
  but the ~200 lines of cash-target/deployment-sizing logic (`_project_cash`, min-deploy floor,
  "too small" rejection, hold-cash thesis path) still have no direct coverage. Extend that file.

### Medium Priority
- [ ] **Smarter research agent** — None of the three parts exist. No sentiment scoring anywhere in
  `src/`; no upcoming-earnings calendar (only backward-looking 8-K ingestion via
  `scripts/ingest_sec_filings.py`, which is offline, not in the daily pipeline); no technical
  indicators — the only price features are raw 5d/30d returns (`src/research/market_context.py:48`).
- [ ] **Conviction tracking over time** — Prior stance already reaches the next cycle: theses are
  extracted per run (`src/memory/extractors.py:37`), retrieved symbol-scoped
  (`src/memory/retriever.py:69`), and rendered into the PM prompt
  (`src/agents/portfolio_manager.py:12`). What's missing is the *time series* — `conviction` exists
  only within a single run's debate (`src/agents/debate.py:19`) and is never compared across days.
- [ ] **Backtest framework** — `scripts/backfill.py:25` is still `# TODO: implement historical
  simulation` inside an empty date loop. Note `src/experiments/comparison.py` is *not* this: it
  compares the live fund to baselines over recorded history (post-hoc attribution, not a backtest).
- [ ] **Multi-model live calibration** *(high leverage for the launch; owner has Groq credits, will
  plug in providers)* — Run the same `market_calls` prompt through several providers each cycle
  (Claude, Groq/Llama, the current gpt-5.6-luna), tag each prediction with the model that made it,
  and publish one calibration curve per model. Turns the launch artifact from "I scored an LLM's
  predictions" into "**Claude vs Llama vs GPT — whose stated confidence is actually honest**," with
  live dated receipts. Directly amplifies [Reposition the launch around calibration]. Build is
  modest: the gateway already routes by `(provider, model)` tier (`src/config.py:74`, fallback slot
  at `:79`), so add a per-model call in `record_market_calls` and a `model` field on the prediction;
  the scorer (`prediction_scorer.py`) and the decision-page Market-calls table already generalize.
  Cost is trivial (~$1–2/mo even on Sonnet; cents on Haiku/Groq). **Scope guard:** spend on the
  *comparison across models*, NOT on making the single fund smarter — `make eval-compare` already
  measured that bigger models don't move decision quality on this eval set (`src/config.py:69-72`),
  so extra reasoning calls for one fund are low-ROI.

### Low Priority
- [ ] **Slack/Discord notifications** — Post daily summaries to a channel. The only outbound
  channel today is X/Twitter (`src/social/twitter.py`).
- [ ] **Memory retrieval reaches only the alphabetically-early names** — `extract_memory_symbols`
  (`src/main.py`) takes every holding plus `research["symbols"][:12]`, and that list is sorted, so
  the slice is an alphabetical prefix. 13 of the 34 universe names are unreachable by memory today
  and all 13 are unheld. Holdings get guaranteed inclusion; everything else plays a lottery on its
  ticker. Found 2026-08-07 while tracing why the fund almost never opens a new position — see the
  incumbency findings in `docs/`.

### Recently Completed

- [x] **No same-day rebuy of a just-sold name** *(2026-07-09, #74)* — the rebalancer was blind to the
  PM's sells and could redeploy cash straight back into a name just trimmed (self-contradictory
  "SELL 50 · BUY 58", seen on 2 of 14 days). `RebalanceChecker.check()` now excludes symbols sold
  this cycle from the deployment prompt AND drops any such BUY after risk review.
- [x] **HOLDs no longer logged as "rejected trades"** *(2026-07-09, #68)* — the min-trade-confidence
  gate fired on HOLDs (no-ops) before the HOLD skip, so 31 of 32 historical "rejected trades" were
  phantom HOLDs. Added the `action != "HOLD"` guard in `risk_manager.py`; filtered HOLDs from every
  surface that renders rejected trades (journal, decision pages, MCP).
- [x] **Better daily tweets** *(2026-07-09, #75)* — dropped the cash%/position-count status-report
  filler; tweets now lead with the trade thesis, cite the news catalyst behind it, and surface the
  fund's sharpest scored call. `tweet_generator.py` + `prompts/tweet_writer.txt` (v2).
- [x] **Ablation harness (V1-1 machinery half)** *(2026-07-08, #66)* — `make eval-ablate` scores
  full vs no-memory vs no-debate on the eval set with a fixed judge; result panel on the dashboard.
  See `docs/ROADMAP-V2.md` V1-1. Also fixed a latent no-timeout hang on the LLM client.
- [x] **Stop-loss / take-profit rules** — `src/agents/risk_events.py` emits full-exit SELLs at
  `STOP_LOSS_PCT` (0.15) and `TAKE_PROFIT_PCT` (0.40), both env-configurable. Wired at
  `src/main.py:182`; system exits supersede LLM trades for the same symbol and still pass through
  `RiskManagerAgent`.
- [x] **Sector concentration limits** — `RiskManagerAgent.review()` seeds a live sector-exposure
  ledger and rejects or share-caps BUYs that would breach `MAX_SECTOR_CONCENTRATION`
  (`risk_manager.py:53,98-132`). SELLs are exempt by design. Correlation remains open (above).
- [x] **Historical performance dashboard** — Ships at `public/dashboard.html`: Chart.js performance
  and allocation charts, plus a sortable holdings table with position-level P&L, fed by
  `src/reporting/public_exporter.py`. **The site lives in `public/`, not `web/`** — the `web/`
  directory was empty scaffolding and has been removed.
- [x] **Configurable watchlist** — Now `config/watchlist.yaml` (33 symbols), loaded and validated
  in `src/config.py:127`. No hardcoded list remains.
- [x] **Tests** — 50 test files under `tests/`, including `test_risk_manager.py`,
  `test_risk_engine_v2.py`, and `test_portfolio_engine.py`. The rebalance checker is the one gap
  from the original entry and is tracked as its own item above.
- [x] **HTML report improvements** — Interactive charts and position-level P&L landed in the
  dashboard rather than in the report generator.

## Distribution & SEO

Done (2026-07-07): `public/robots.txt`, per-page `canonical` / `meta description` / `og:url` /
page-specific `og:title` + `og:description` on all six pages, JSON-LD (`WebSite` + `Person`) on
`index.html`, prerendered per-day decision pages, and a generated `sitemap.xml`.

The framing to hold onto: **this project's rare asset is that it generates unique, dated,
opinionated content every single day.** Everything below follows from that.

### High Priority

### Decision pages — follow-up

All four shipped 2026-07-09 (PRs #69, #70, #71). Kept as a record.

- [x] **Fixed the `created_at` string comparison** *(latent bug)* (#69) —
  `decision_pages.latest_per_date()` now parses `created_at` to an aware UTC datetime
  (`_created_at()`) before comparing, so an offset timestamp (`+05:30`) can't silently publish a
  superseded run. Regression test covers it.
- [x] **Gated thin pages out of the index** (#69) — days with no debate, no trade, and no market
  calls get `<meta name="robots" content="noindex,follow">` and are excluded from `sitemap.xml`,
  kept as permalinks (`_is_substantial()`). 5 of 14 days are held today; the gate opens on its own.
- [x] **Traded symbols in `<title>`/`<h1>`** (#69) — `AI fund buys AAPL — July 7, 2026`
  (buys/sells + tickers), falling back to the plain title on hold days. URL unchanged.
- [x] **Symbol hub pages** *(`/symbols/<TICKER>.html`)* (#70, extended #71) — one page per ticker
  aggregating every decision that touched it, newest first, each card linked to its day page, plus
  a `/symbols/` index and sitemap entries. #71 then generates a hub for **every** universe ticker
  (noindexed placeholder when empty) so a symbol link never 404s, and links every ticker mention
  across the site (decision pages, live journal, dashboard holdings/KPIs, predictions) to its hub.
  `_symbol_touches()` / `render_symbol_page()` / `_symbol_link()` in `decision_pages.py`.

### Recently Completed

- [x] **Rate limit handling** *(2026-08-08, #109)* — yfinance and the news client both caught bare
  `Exception` and returned empty, so a 429 was indistinguishable from a delisted ticker and the fund
  decided on partial data while reporting success. Raised errors now retry with exponential backoff;
  an *empty* result is not retried (that is a delisted ticker, not a failure). A batch losing more
  than `MARKET_DATA_MAX_MISSING_PCT` (25%) raises `MarketDataUnavailable` instead of returning gaps.
  News deliberately goes the other way — it degrades to empty rather than failing a run.

- [x] **Publish weekly investor letters as pages** *(verified done 2026-08-08)* — dated permalinks
  at `public/letters/YYYY-MM-DD.html` plus an index and sitemap entries, built by
  `src/reporting/letter_pages.py` following `decision_pages.py`. The "watch out" on that entry is
  also resolved: `weekly-letter.yml:68` commits `data/investor_letters.jsonl` and `public/letters`,
  so per-week history accumulates — 4 letters are in the committed store. Letters were reachable
  only via `sitemap.xml` until 2026-08-08 (#100) added them to the nav.

- [x] **Delete dead `src/reporting/html_report.py`** *(2026-08-08)* — zero references anywhere in
  `src/`, `scripts/`, `tests/`, `mcp_server/` or `evals/`. The README also advertised "Markdown and
  HTML performance reports"; that claim went in #105.

- [x] **GitHub repo metadata** *(2026-08-07)* — homepage set to `https://glasshousefund.com`
  (verified HTTP 200); description rewritten to lead with the scoring and MCP hooks rather than
  "AI-powered portfolio management system"; 12 topics added (`llm-agents`, `mcp`,
  `model-context-protocol`, `evals`, `calibration`, `ai-engineering`, `langgraph`, `llm`,
  `paper-trading`, `agentic-ai`, `qdrant`, `python`). Live now — the repo is public. Reword with
  `gh repo edit --description "…"` if the launch framing shifts.

- [x] **Wait for resolved predictions before launching** *(gate cleared 2026-08-07)* — the target was
  ~50–100 resolved. **As of 2026-08-07: 244 predictions, 177 scored, 67 open; 103 correct = 58.2%
  hit rate**, scored over 2026-07-13 → 2026-08-07. (The old *41 resolved / 109 total* figure was
  from 2026-07-17; note the store's status value is `scored`, not `resolved`.) N is no longer the
  blocker for [Reposition the launch around calibration] — that item is now the only thing between
  here and a launch.

  **The calibration curve has the shape the launch needs — the model is overconfident:**

  | stated confidence | n | actual | gap |
  |---|---|---|---|
  | 0.5–0.6 | 38 | 57.9% | **+3.2** |
  | 0.6–0.7 | 79 | 53.2% | **−9.2** |
  | 0.7–0.8 | 56 | 67.9% | −4.3 |
  | 0.8–0.9 | 4 | 25.0% | **−56.2** |

  **Brier: 0.2464** — barely better than the 0.25 a coin flip scores. Every bucket above 0.6 is
  overconfident, and the four most confident calls went 1-for-4 (don't lead with that bucket alone,
  n=4). By horizon: 5d 80/136 (58.8%), 30d 19/34 (55.9%).

  Two asymmetries worth a paragraph each in the writeup: **UNDERPERFORM calls hit 66.7% (n=84) but
  OUTPERFORM only 44.4% (n=45)** — the fund is good at spotting laggards and near-random at picking
  winners, which is the opposite of how a stock-picker markets itself. And `became_trade` is true
  for only **2** scored calls, so the "all views vs traded-only" two-curve plan is not viable yet;
  the traded curve has no N. Either drop it or wait.

  *How the N was reached, kept because it explains the data's shape:* **throughput was fixed on
  2026-07-08** — predictions used to spawn only from BUYs (~7 in a month, biased toward high
  conviction). Every run now records a directional call for every researched name at 5d and 30d
  horizons, decoupled from trading (`record_market_calls` in `main.py`,
  `PredictionStore.create_call`). Non-overlapping windows per (symbol, horizon) keep samples
  independent, and the 5d horizon is why a curve exists ~3 weeks in rather than the ~6–9 months the
  BUY-only path implied. N accumulates *forward* only — no live backfill without lookahead. That
  decoupling is also why `became_trade` is near-zero: calls are recorded for the whole research
  universe, but the fund only trades a couple of names a day.

- [x] **Submit the sitemap in Google Search Console** (2026-07-08) — Domain property, verified by
  TXT record. Note the DNS lives on Vercel nameservers even though GitHub Pages serves the site, so
  the record goes in the Vercel dashboard, not GitHub. The sitemap grew from 6 URLs to 19 after the
  decision pages landed; it regenerates every run.

- [x] **Prerender decisions to static URLs** — `src/reporting/decision_pages.py`, wired into
  `PublicExporter.export()` so it runs every daily cycle. One page per *trading day*, not per
  symbol: `decisions.jsonl` holds one row per **run**, and a day can carry many runs (2026-06-13
  has 13). The last run of a date is that day's decision. Per-symbol pages would have sliced one
  portfolio-wide debate into near-duplicate stubs. `decisions.html` stays as the live journal and
  now links each day to its permalink. Crawlable text went from 281 chars (JS-rendered — what a
  crawler sees) to a **median of 1,975** per page; the three days that have a debate transcript
  reach ~7,300. Do not quote the 7,300 alone — it is the best page, not the typical one. See the
  thin-page gate above.
- [x] **Generate `sitemap.xml` at export time** — `decision_pages.build_sitemap()` emits the static
  pages plus every decision page. Dynamic pages get the latest decision date as `lastmod`; the two
  static pages get none, so the file doesn't churn daily.

### Medium Priority
- [ ] **Reposition the launch around calibration** — Do *not* launch as "an AI portfolio manager":
  it's a crowded, low-credibility genre whose implicit claim ("I beat the market") nobody believes.
  Lead instead with *"I made an LLM make N stock predictions and then actually scored them"* —
  the Brier score and confidence-calibration curve are the artifact. Secondary hook: the read-only
  MCP server ("point Claude at a real fund's decision history and interrogate it"), currently
  buried as README bullet 11.
- [ ] **Draft the retrospective** — `docs/article-notes.md` and `docs/incidents.md` are already the
  skeleton. `incidents.md` gained the two August ops incidents on 2026-08-07 (#92, #93).
