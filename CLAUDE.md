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

Done (2026-07-07): `public/robots.txt`, per-page `canonical` / `meta description` / `og:url` /
page-specific `og:title` + `og:description` on all six pages, JSON-LD (`WebSite` + `Person`) on
`index.html`, prerendered per-day decision pages, and a generated `sitemap.xml`.

The framing to hold onto: **this project's rare asset is that it generates unique, dated,
opinionated content every single day.** Everything below follows from that.

### High Priority
- [ ] **Publish weekly investor letters as pages** — **Blocked, and not by the plumbing.** No letter
  has ever published: `data/investor_letters.jsonl` does not exist and the only weekly-letter run
  (2026-07-05) failed. `_window_return` yields decimals (`0.0231`), the model correctly writes
  "2.31%", and the grounding judge calls that a *material* fabrication — so
  `investor_letter.py:203` blocks publication. The judge's own prompt says equivalent phrasing must
  be minor (`src/scoring/grounding.py:59-67`). Fix the false positive first; only then build
  `/letters/YYYY-MM-DD.html` + an index, following `decision_pages.py`. Note the original entry
  claimed letters "only reach the dashboard" — they reach nothing.
### Decision pages — follow-up

Shipped, live, and working. These four came out of reviewing the result. Ordered by
leverage; the first is a latent bug, not a nicety.

- [ ] **Fix the `created_at` string comparison** *(bug — fails silently)* —
  `decision_pages.latest_per_date()` picks a day's decision by comparing `created_at`
  lexicographically. All 38 rows today are fixed-width UTC (`...083605Z`), so it's correct. The
  moment one row carries an offset (`+05:30`), string ordering picks the *wrong* run and publishes
  a superseded decision — with no error. Parse to `datetime` before comparing.
- [ ] **Gate thin pages out of the index** — Of the 12 published pages, **9 are under 2,500 chars**
  and 5 have neither trades nor a debate (median 1,975 total, 1,649 after 326 chars of nav/footer
  chrome). The debate transcript only starts on 2026-07-03; everything earlier is backfill from a
  system that had no debate. Publishing 9 thin pages to gain 3 rich ones is a bad trade at N=12 and
  a good one at N=250. Keep them as permalinks and audit trail, but exclude from `sitemap.xml` and
  mark `<meta name="robots" content="noindex,follow">` until a day clears a bar — has a debate, or
  at least one approved trade. Today that indexes 6 and holds 6; the gate opens on its own as the
  corpus matures.
- [ ] **Put the traded symbols in `<title>` and `<h1>`** — Currently `AI fund decision — July 7,
  2026`. The title is the strongest on-page signal and carries zero entity signal today; nobody
  searches for a date. `AI fund buys AAPL — July 7, 2026` costs nothing and does not change the URL.
- [ ] **Symbol hub pages** *(`/symbols/NVDA.html`)* — The entity query we actually care about
  ("why did an AI fund sell NVDA") is served by neither a date page nor a per-symbol *decision*
  stub. It wants one page per symbol, aggregating every decision that ever touched it, newest
  first, cross-linked to the day pages. Entity hub + chronological detail is the standard
  programmatic-SEO structure, and hubs get *richer* over time where per-day-per-symbol stubs get
  thinner. ~33 pages total, not 15/day. Gate at ~3 mentions so day-one hubs aren't empty. Data is
  already in `decisions.jsonl`; reuse the shell/sitemap/index patterns in `decision_pages.py`.
  **Do not confuse this with per-symbol decision pages, which are correctly rejected above.**

### Recently Completed

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
- [ ] **Wait for resolved predictions before launching** — Launch at ~50–100 resolved predictions.
  An LLM that is *confidently wrong*, with receipts, is a better story than one that wins — but only
  once N is large enough to mean anything. **Throughput was fixed on 2026-07-08**: predictions used
  to spawn only from BUYs (~7 in a month, biased toward high conviction). Now every run records a
  directional call for every researched name at 5d and 30d horizons, decoupled from trading
  (`record_market_calls` in `main.py`, `PredictionStore.create_call`). Non-overlapping windows per
  (symbol, horizon) keep samples independent; the 5d horizon means the first curve gets shape within
  ~2 weeks rather than the ~6–9 months the BUY-only path implied. `became_trade` lets the writeup
  show two curves (all views vs traded-only). N still accumulates *forward* from the ship date — no
  live backfill without lookahead.
- [ ] **Draft the retrospective** — `docs/article-notes.md` and `docs/incidents.md` are already the
  skeleton.
