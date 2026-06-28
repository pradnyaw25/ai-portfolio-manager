# AI Portfolio Manager Roadmap

This list tracks open engineering work only. Completed foundation work such as
run IDs, run status export, step-function refactoring, typed run state, and local
`make` commands has been removed from the active roadmap.

## Near-Term Priorities

1. Complete the LangGraph migration.
   * Make the graph runner the primary daily workflow once behavior matches the existing runner.
   * Add conditional routing for memory failures, empty decisions, rejected trades, and execution failures.
   * Add per-node failure capture so failed runs still export status and diagnostics.
   * Add an optional human approval checkpoint before trade execution.
   * Add parity tests or fixtures comparing standard-run and graph-run outputs.

2. Add Twitter/X publishing integration.
   * Keep generated tweets as drafts by default.
   * Add dry-run versus live-post mode controlled by environment config.
   * Publish via Twitter/X API only when explicitly enabled.
   * Store publish status, tweet ID, timestamp, and API errors in a durable social-post log.
   * Add an AI safety/evaluator step to reject hype, unsupported claims, and compliance-risk language.
   * Add tests for disabled publishing, successful publishing, and API failure handling.

3. Build Risk Engine V2.
   * Add sector exposure limits using repo-owned symbol metadata.
   * Add max single-position allocation checks.
   * Add portfolio concentration and cash-deployment guardrails.
   * Add correlation-aware diversification checks.
   * Add max daily and weekly turnover controls.
   * Add deterministic stop-loss and take-profit SELL proposals.
   * Journal capped, rejected, and system-generated trades as first-class risk events.

4. Move portfolio inputs into typed config.
   * Move the hardcoded watchlist out of `src/research/market_context.py`.
   * Add typed config files for watchlists, sector metadata, risk limits, and model settings.
   * Validate config at startup with clear error messages.

## AI Architecture

1. Add a model/provider abstraction.
   * Support OpenAI, Anthropic, and local or cheaper fallback models behind one interface.
   * Add model routing: cheaper models for summaries, stronger models for final decisions.
   * Track model name, provider, prompt version, latency, token usage, and estimated cost.
   * Add graceful fallback behavior when a provider fails.

2. Introduce multi-agent research and decision flow.
   * Add bull analyst, bear analyst, risk analyst, and portfolio manager roles.
   * Add a critic/evaluator agent before final journaling.
   * Add agent debate or compare-and-rank step for high-impact trades.
   * Require structured outputs from every agent.

3. Add structured tool calling.
   * Expose market data, news, memory retrieval, benchmark lookup, and portfolio actions as typed tools.
   * Validate tool inputs and outputs before they enter the decision state.
   * Record tool calls in the decision trace for observability.

4. Add prompt and decision versioning.
   * Version prompts and schemas used by each agent.
   * Store prompt version with decisions, reports, predictions, and tweets.
   * Add regression tests for prompt output shape and risk compliance.

## Memory And RAG

1. Upgrade the Qdrant memory schema.
   * Store typed memories: thesis, trade, mistake, macro regime, earnings event, and risk lesson.
   * Add metadata for symbol, sector, date, run ID, source type, and outcome.
   * Deduplicate and score memory quality before indexing.

2. Automate memory ingestion.
   * Ingest each completed report, decision, trade set, and prediction outcome after the daily run.
   * Add backfill tooling for historical reports and decision journals.
   * Export memory ingestion status in run diagnostics.

3. Add retrieval evaluation.
   * Build fixtures with known prior decisions and expected retrieved memories.
   * Score retrieval relevance, freshness, and source diversity.
   * Add citations from retrieved memories into AI decisions.

4. Add lessons-learned synthesis.
   * Summarize successful and failed theses over time.
   * Extract recurring risk mistakes and missed opportunities.
   * Feed lessons back into future portfolio decisions.

## Evaluation And Observability

1. Build an AI decision eval harness.
   * Create golden scenarios for bull market, crash, high cash, overconcentration, missing data, and stale memory.
   * Score schema validity, factual grounding, risk compliance, and actionability.
   * Track eval results across models, prompt versions, and code changes.

2. Add hallucination and grounding checks.
   * Verify claims against available market context, news, memory, and portfolio state.
   * Flag unsupported claims before journaling, reporting, or tweeting.
   * Store evaluator findings with each decision.

3. Improve run diagnostics.
   * Add durable run history instead of only latest run status.
   * Emit structured JSON logs with run ID, graph node, model, latency, token usage, and error details.
   * Add failure-status export when the daily run crashes.
   * Add cost and latency summaries per run.

4. Add dashboard observability views.
   * Decision trace: inputs, memories, tool calls, agent outputs, risk review, and final trades.
   * Model cost and latency dashboard.
   * Rejected trades and risk adjustments table.
   * Prediction calibration dashboard.
   * Run comparison page for legacy runner versus LangGraph runner.

## Research Intelligence

1. Build Market Context V2.
   * Add 5D, 30D, and 90D returns.
   * Add volatility, market cap, sector, benchmark-relative performance, and drawdown.
   * Add sector rotation and macro regime indicators.

2. Improve news and catalyst intelligence.
   * Prioritize news for current holdings and high-conviction candidates.
   * Add earnings-date awareness.
   * Summarize earnings calls, analyst upgrades/downgrades, and major headlines.
   * Add sentiment scoring with source citations.

3. Expand candidate generation.
   * Combine current holdings, configurable watchlist, momentum names, biggest losers, earnings candidates, and news catalysts.
   * Rank candidates with deterministic features before asking an LLM for analysis.
   * Store candidate-generation inputs and scores for auditability.

## Forecasting And Product Surface

1. Deepen prediction tracking.
   * Track forecast horizon, thesis, confidence, start price, end price, benchmark return, and outcome.
   * Add confidence calibration metrics including Brier score.
   * Compare AI recommendations against actual executed trades.

2. Improve public dashboard.
   * Add portfolio versus SPY and QQQ charts.
   * Add cash allocation, sector allocation, and concentration warnings.
   * Add top holdings table with gain/loss and portfolio weight.
   * Add recent trades, rejected trades, and generated risk events.

3. Add investor-facing publishing workflows.
   * Generate weekly investor letter with performance, winners, losers, portfolio changes, and market outlook.
   * Add optional Twitter/X thread mode for weekly summaries.
   * Keep all publishing workflows auditable and disabled by default in local development.
