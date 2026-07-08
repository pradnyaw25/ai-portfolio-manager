# CLAUDE.md

## Project Overview

AI Portfolio Manager — an LLM-powered paper trading system that runs a daily cycle:
**Research → Decision → Risk Check → Rebalance Check → Execute → Journal → Report**

The system uses LLM agents to analyze markets, make trade decisions, and manage a simulated $1M portfolio. It enforces risk guardrails deterministically (position sizing, turnover limits, confidence thresholds) and requires the AI to justify holding excess cash.

## Architecture

- `src/main.py` — Orchestrates the daily cycle
- `src/agents/` — LLM-powered agents:
  - `researcher.py` — Gathers prices, movers, news for holdings + watchlist
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
- Data files (`data/`, `reports/`) are gitignored — don't commit generated output
- The decision journal (`data/decisions.jsonl`) is the audit trail — always include `cash_thesis` and `rebalance_trades` when saving

## README Maintenance

**Always keep `README.md` up to date** when adding features, changing the pipeline, or modifying the project structure. The README is the public face of this project. If you add a new agent, config option, or pipeline step, update the README to reflect it.

## Future Tasks

> Reconciled against the code on 2026-07-07. Completed items moved to "Recently Completed"
> below rather than deleted, so the backlog keeps its history.

### High Priority
- [ ] **Correlation-aware diversification** — Sector concentration *is* enforced
  (`risk_manager.py:98-132`, 40% cap). Correlation is not: there is no correlation code anywhere
  in `src/`. Two names in different GICS sectors that move together still pass every check.
- [ ] **Unit-test the rebalance checker** — `src/agents/rebalance_checker.py` holds ~200 lines of
  cash-target logic and has no direct test. It appears in `tests/test_daily_graph_integration.py`
  only as a stubbed graph node, so the real logic is never exercised.

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

### Low Priority
- [ ] **Slack/Discord notifications** — Post daily summaries to a channel. The only outbound
  channel today is X/Twitter (`src/social/twitter.py`).
- [ ] **Rate limit handling** — Graceful retry/backoff for the data sources. Note the original
  entry named Alpha Vantage, which this codebase has never used. The real gaps are yfinance
  (`src/data_sources/market_data.py:22`) and the news client (`src/data_sources/news.py:71`), both
  of which swallow exceptions and silently degrade to empty results on a 429. Exponential backoff
  already exists for the LLM gateway (`src/llm/gateway.py:299`) and is a reasonable model to copy.
- [ ] **Delete dead `src/reporting/html_report.py`** — Never imported or called; the pipeline uses
  `MarkdownReportGenerator` (`src/main.py:31`). Its static P&L table was superseded by the dashboard.

### Recently Completed

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

Done (2026-07-07): `public/robots.txt`, `public/sitemap.xml`, and per-page `canonical` /
`meta description` / `og:url` / page-specific `og:title` + `og:description` on all six pages.
JSON-LD (`WebSite` + `Person`) on `index.html`.

The remaining work, in leverage order. The framing to hold onto: **this project's rare asset is
that it generates unique, dated, opinionated content every single day — and currently publishes
none of it as an indexable page.** Everything below follows from that.

### High Priority
- [ ] **Prerender decisions to static URLs** — `decisions.html` client-fetches `decisions.jsonl`,
  so hundreds of decisions collapse into one URL with no server-rendered text. Emit
  `/decisions/YYYY-MM-DD-SYMBOL.html` at export time with the real debate text, each with its own
  title/description/canonical, and add each to the sitemap. This is the actual SEO unlock — it
  turns one thin page into hundreds of long-tail pages ("why did an AI fund sell NVDA in June")
  where this site plausibly *is* the best result on the internet.
- [ ] **Publish weekly investor letters as pages** — `scripts/weekly_letter.py` generates letters
  that only reach the dashboard. Publish each to `/letters/YYYY-MM-DD.html` plus an index at
  `/letters/`, add to sitemap. Best long-tail content the system produces; currently discarded.
- [ ] **Generate `sitemap.xml` at export time** — Once the two items above land, the hand-written
  sitemap goes stale immediately. Build it from the decision/letter/page set.

### Medium Priority
- [ ] **GitHub repo metadata** *(owner decision — publishes immediately)* — Repo has `topics: null`,
  empty `homepageUrl`, and a stale generic description that never names Glasshouse Fund. Set the
  homepage to `https://glasshousefund.com`, rewrite the description to lead with evals + MCP, and
  add topics (`llm-agents`, `mcp`, `evals`, `ai-engineering`, `paper-trading`, …).
- [ ] **Reposition the launch around calibration** — Do *not* launch as "an AI portfolio manager":
  it's a crowded, low-credibility genre whose implicit claim ("I beat the market") nobody believes.
  Lead instead with *"I made an LLM make N stock predictions and then actually scored them"* —
  the Brier score and confidence-calibration curve are the artifact. Secondary hook: the read-only
  MCP server ("point Claude at a real fund's decision history and interrogate it"), currently
  buried as README bullet 11.
- [ ] **Wait for resolved predictions before launching** — Each BUY spawns a 30-day prediction and
  the repo is ~1 month old, so almost nothing has resolved and the calibration curve is still
  noise. Launch at ~50–100 resolved predictions. An LLM that is *confidently wrong*, with receipts,
  is a better story than one that wins — but only once N is large enough to mean anything.
- [ ] **Draft the retrospective** — `docs/article-notes.md` and `docs/incidents.md` are already the
  skeleton.
