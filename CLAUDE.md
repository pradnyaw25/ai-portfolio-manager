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

### High Priority
- [ ] **Sector/correlation diversification** — Risk manager should check sector concentration, not just position size. Avoid loading up on 5 tech stocks.
- [ ] **Stop-loss / take-profit rules** — Auto-generate SELL trades when a position drops >15% or gains >40% from cost basis.
- [ ] **Historical performance dashboard** — Build a web UI (`web/` dir) to visualize portfolio history, P&L curves, and trade logs.

### Medium Priority
- [ ] **Smarter research agent** — Add sentiment scoring, earnings calendar awareness, and technical indicators (RSI, moving averages).
- [ ] **Multi-day thesis tracking** — Track conviction over time. If the AI was bullish on AAPL 3 days ago, surface that context in the next cycle.
- [ ] **Backtest framework** — Run the strategy against historical data to validate before live paper trading.
- [ ] **Configurable watchlist** — Move the hardcoded 15-symbol watchlist to config or a YAML file.

### Low Priority
- [ ] **Slack/Discord notifications** — Post daily summaries to a channel.
- [ ] **HTML report improvements** — Interactive charts, position-level P&L breakdown.
- [ ] **Rate limit handling** — Graceful retry/backoff for Alpha Vantage and news API limits.
- [ ] **Tests** — Unit tests for risk manager, rebalance checker, and portfolio engine.

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
