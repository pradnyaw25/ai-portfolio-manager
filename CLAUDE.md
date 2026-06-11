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
