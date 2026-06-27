# AI Portfolio Manager Roadmap

## Next Codex Tasks

Recommended next work, in order:

1. [Done] Add run IDs across the daily cycle.
   * Generate one `run_id` per run.
   * Carry it through logs, decisions, trades, reports, predictions, and public exports.
   * Use this as the foundation for debugging and dashboard status.

2. [Done] Add a run status export.
   * Create `public/run_status.json`.
   * Include latest run time, success/failure, memory status, trades executed, warnings/errors, ending portfolio value, and cash percentage.
   * Add a dashboard panel for this status.

3. [Done] Refactor `src/main.py` into explicit step functions.
   * Suggested steps: load portfolio, mark to market, build research context, retrieve memory, decide trades, review risk, check rebalance, execute trades, journal run, export public artifacts.
   * Keep behavior unchanged at first.

4. Introduce a typed `PortfolioRunState`.
   * Add a dataclass that carries snapshot, market context, memory result, raw decision, risk review, rebalance result, executed trades, warnings, errors, and run metadata.
   * This prepares the codebase for LangGraph without migrating all at once.

5. Add sector diversification guardrails.
   * Add symbol-to-sector metadata.
   * Reject or cap trades that overconcentrate the portfolio in one sector.

6. Add stop-loss and take-profit rules.
   * Generate deterministic SELL proposals for positions down more than 15% from average cost or up more than 40%.
   * Prefer partial exits unless a stronger rule says otherwise.

7. Make the watchlist configurable.
   * Move hardcoded `WATCHLIST` out of `src/research/market_context.py`.
   * Use config, YAML, or another simple repo-owned data file.

8. Improve local run UX.
   * Add a `Makefile` or similar commands for test, run, dashboard, and memory ingest.

## Phase 1 — Credibility & Observability

### P0: Fix Portfolio Accounting

* Verify mark-to-market updates current prices correctly
* Verify total portfolio value changes daily
* Verify benchmark calculations
* Add unit tests for portfolio valuation
* Add unit tests for benchmark performance

### P1: Dashboard Improvements

* Portfolio vs SPY chart
* Portfolio vs QQQ chart
* Cash allocation over time chart
* Sector allocation chart
* Top holdings table
* Recent trades table

### P2: Public Decision Journal

Create `/decisions.html`

Display:

* Market summary
* Portfolio assessment
* Cash thesis
* Trade recommendations
* Executed trades
* Confidence scores
* Sources used
* Rejected trades

### P3: Better Tweets

Replace generic tweets with factual updates.

Include:

* Portfolio value
* Daily return
* Benchmark comparison
* Trades executed
* Cash percentage
* Key thesis

Avoid:

* Emojis
* "Excited"
* Generic hype language

---

## Phase 2 — Research Quality

### P4: News Pipeline

For each holding:

* Latest headlines
* Earnings headlines
* Analyst upgrades/downgrades

Market headlines:

* S&P 500
* Nasdaq
* Macro news
* Fed news

### P5: Market Context Builder V2

Add:

* 5D return
* 30D return
* 90D return
* Market cap
* Sector
* Volatility
* Benchmark performance

### P6: Candidate Generation

Current:

* Fixed watchlist

Future:

* Current holdings
* Watchlist
* Top momentum names
* Biggest losers
* Earnings candidates

---

## Phase 3 — Forecasting Engine

### P7: Prediction Tracking

Store:

Prediction:

* Symbol
* Thesis
* Confidence
* Horizon (30/60/90 days)

Track:

* Start price
* End price
* Benchmark return
* Success/failure

### P8: Calibration Dashboard

Metrics:

* Accuracy
* Precision
* Confidence calibration
* Brier score

Display:

* 50% confidence predictions
* 70% confidence predictions
* 90% confidence predictions

---

## Phase 4 — Multi-Agent Architecture

### P9: Bull Analyst

Produces:

* Bull thesis
* Upside case

### P10: Bear Analyst

Produces:

* Risk thesis
* Downside case

### P11: Portfolio Manager

Reads:

* Bull case
* Bear case
* Risk analysis

Makes final decision.

### P12: Risk Manager V2

Checks:

* Max position size
* Sector exposure
* Portfolio concentration
* Turnover limits

---

## Phase 5 — Memory & RAG

### P13: Research Archive

Store:

* Daily reports
* Decisions
* Predictions
* Trades
* Investor letters

### P14: Qdrant Memory

Questions like:

* What did we believe about NVDA 6 months ago?
* Which theses worked best?
* Which sectors have performed best?

---

## Phase 6 — Public Product

### P15: Weekly Investor Letter

Every Friday:

Include:

* Weekly performance
* Winners
* Losers
* Portfolio changes
* Market outlook

### P16: X/Twitter Automation

Automatically publish:

* Daily update
* Weekly letter
* Major portfolio changes

### P17: Public API

Expose:

* Holdings
* Performance
* Predictions
* Benchmark comparison

---

## Phase 7 — Advanced Experiments

### P18: Strategy Backtesting

Compare:

* Buy & Hold
* SPY
* AI Portfolio

### P19: Model Comparisons

Run:

* GPT strategy
* Claude strategy
* Multi-agent strategy

Track performance separately.

### P20: Paper Hedge Fund Dashboard

Show:

* Sharpe ratio
* Volatility
* Drawdown
* Alpha vs benchmark
* Prediction accuracy
* Sector attribution
