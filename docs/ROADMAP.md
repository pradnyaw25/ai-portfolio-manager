# AI Portfolio Manager — Assessment & Roadmap V1 (July 2026)

> **Superseded by [`ROADMAP-V2.md`](ROADMAP-V2.md).** All six phases below were
> executed; V2 is the current plan. This document is kept for provenance and its
> still-valid rationale (target architecture, §7 not-worth-building).

A principal-engineer review of the project as of 2026-07-02 (89 commits, ~4,400 LOC src
+ ~1,400 LOC tests), and the phased roadmap derived from it. The actionable task list
lives in [`.claude/TODO.md`](../.claude/TODO.md); this document is the rationale.

**Project goal:** a learning platform for modern AI engineering (LLMs, RAG, vector DBs,
LangGraph, evals, agent infra) that doubles as a senior/staff-level portfolio piece.
Trading performance is secondary to engineering sophistication and demonstrable skills.

---

## 1. Current-State Assessment

**TL;DR: the project is meaningfully further along than its own docs claim, and the
bones are good. But the layer that's supposed to be the showcase — the LLM
engineering — is currently the weakest layer in the codebase.**

What exists today:

- **A real daily pipeline** (17 steps): mark-to-market → research context → Qdrant
  memory retrieval → LLM decision → deterministic risk guardrails → rebalance
  enforcement → execution → journaling → prediction tracking → report → tweet →
  public export → memory ingestion.
- **A working memory/RAG layer**: Qdrant with typed memories (thesis, trade,
  risk_lesson, macro_regime), deterministic UUID5 point IDs for idempotent upserts,
  grouped retrieval, memory *citations* in decisions with warnings for hallucinated
  IDs, and retrieval eval fixtures. Above-average for a side project.
- **A SEC 10-K ingestion pipeline** (weekly GitHub Action): EDGAR fetch, section
  extraction (Items 1, 1A, 7, 7A), rate-limited, cached, memory-health export.
- **Prediction tracking**: every BUY spawns a 30-day "beat SPY" prediction that gets
  scored won/lost.
- **An opt-in LangGraph runner** with guarded nodes, per-step failure capture, and
  typed run state.
- **Automation**: scheduled GH Actions with a market-hours guard, GitHub Pages
  dashboard, X publishing behind a flag.
- **16 test files**, deterministic risk manager, strong dataclass/type-hint
  discipline, graceful degradation when Qdrant is down.

**Strengths worth preserving:** the deterministic risk layer separated from LLM
judgment; the decision journal as an audit trail with memory citations; run_id
threading; failure-tolerant memory retrieval.

**Honest weaknesses:**

1. **The LLM interface is the weakest layer.** `gpt-4o-mini` hardcoded in three
   files, module-level `OpenAI()` client, raw `json.loads()` on responses with zero
   schema validation, no retries, no temperature control, no token/cost tracking,
   single provider (the `anthropic` dependency is installed and never imported). One
   malformed response kills the whole run.
2. **No tool calling anywhere.** Every agent is prompt-stuffing: context is
   JSON-dumped into a string.
3. **One decision-making agent.** Multi-agent is aspirational — `researcher.py` is
   dead code that `main.py` doesn't call.
4. **No observability.** No tracing, no cost dashboard, no latency tracking, no
   durable run history — only latest-run status.
5. **Evaluation is embryonic.** Retrieval fixtures exist; no decision evals, no
   grounding checks, no calibration metrics (win/loss only, no Brier score).
6. **Data layer is fragile.** Append-only CSV/JSONL with no idempotency (re-running
   a run_id duplicates trades/decisions), no locking, and the deploy pipeline
   force-commits `data/` to main — repo-as-database.
7. **RAG is naive.** Whole 12k-char 10-K sections as single vectors, no chunking
   (langchain-text-splitters installed, unused), regex section detection that fails
   silently on nonstandard filings.

## 2. Gap Analysis

| Capability | Current | Gap to "impressive" |
|---|---|---|
| Structured outputs | JSON mode + raw `json.loads` | Pydantic-validated schemas, retry-on-invalid, versioned |
| Multi-agent | Single PM agent | Bull/bear/risk debate with recorded transcript |
| LangGraph | Linear opt-in runner | Default path, conditional routing, checkpointing, HITL interrupt |
| Tool calling | None | Typed tools for prices, news, memory, portfolio queries |
| Observability | Latest-run JSON | Tracing (Langfuse), per-run cost/latency, durable history |
| Evals | Retrieval fixtures | Decision evals in CI, grounding checks, LLM-as-judge |
| Calibration | Win/loss counts | Brier score, calibration curves, confidence-bucket analysis |
| Model routing | One hardcoded model | Provider abstraction, cheap-vs-strong routing, fallback |
| RAG | Section-sized vectors | Chunking, metadata filters, hybrid search, more sources |
| Data layer | CSV/JSONL, git-as-DB | SQLite with idempotent upserts, decoupled publishing |
| Backtesting | None | Deterministic replay harness |
| Risk engine | Size + turnover + confidence | Sector limits, stop-loss/take-profit, correlation |

## 3. Target Architecture

**A LangGraph-orchestrated multi-agent system sitting on a hardened LLM gateway, with
SQLite as the system of record, Qdrant as long-term memory, evals in CI, and
traces/costs/calibration exposed on the public dashboard.**

```
                        ┌─────────────────────────────────────────┐
                        │  LangGraph Orchestrator (default path)  │
                        │  SQLite checkpointer · HITL interrupt   │
                        │  conditional routing · retry branches   │
                        └──────────────────┬──────────────────────┘
          ┌───────────────┬────────────────┼────────────────┬──────────────┐
     Research node   Debate nodes      PM synthesis     Risk engine    Execution
     (tool-calling)  (bull/bear/risk)  (structured)     (deterministic) (simulator)
          │                │                │
          └────────────────┴────────────────┘
                           │
                 ┌─────────┴──────────┐
                 │    LLM Gateway     │  ← the single choke point
                 │ Pydantic schemas · │
                 │ retries · routing ·│
                 │ cost/latency log · │
                 │ prompt versions    │
                 └─────────┬──────────┘
        ┌────────────┬─────┴──────┬─────────────┐
     OpenAI      Anthropic     Ollama        Langfuse
                               (optional)    (tracing)

  Data: SQLite (runs, trades, decisions, predictions, tool calls — idempotent)
        Qdrant (chunked memories + SEC/earnings RAG, metadata-filtered)
  Evals: golden-scenario harness in CI · retrieval evals · grounding judge
  Surface: GH Pages dashboard (P&L, calibration, decision traces, costs)
         · MCP server exposing the fund to Claude/any client
```

Key decisions:

- **SQLite, not Postgres.** No server needed; transactions, upserts, and
  queryability are. Stop committing raw state to main; keep committing *exports* to
  Pages.
- **One LLM gateway module** through which every call flows — makes routing,
  tracing, evals, fallback, and cost tracking one-time costs instead of per-agent
  costs. Highest-leverage refactor in the repo.
- **LangGraph becomes the only runner.** Delete the legacy orchestration once parity
  tests pass. Two parallel orchestrators is debt, not safety.
- **Langfuse over LangSmith** — self-hostable, open source, better story.

## 4. Product Direction

Run it as an **explainable AI hedge fund, in public**. The differentiator is not
returns — it's radical transparency: every decision traced, every claim cited to
memory, every prediction scored, calibration published, humans able to veto trades.
Honest about being paper trading. Secondary extractions later: the MCP server, and
possibly the decision-audit pattern as a small open-source library.

Explicitly avoided: "portfolio copilot for other people's portfolios" (data
connections, compliance-adjacent, little engineering novelty).

## 5. Phases

| Phase | Theme | Effort | Key deliverables |
|---|---|---|---|
| 0 | Harden the foundation | ~1 wk | LLM gateway, structured outputs, config cleanup, idempotent stores |
| 1 | Orchestration & observability | 1–2 wk | LangGraph default, checkpointing, HITL approval gate, Langfuse |
| 2 | Evals & calibration | ~2 wk | Golden-scenario evals in CI, grounding judge, Brier/calibration dashboard |
| 3 | Multi-agent & tools | 2–3 wk | Bull/bear/risk debate, typed tool calling, model routing |
| 4 | Knowledge layer | ~2 wk | Chunked metadata RAG, earnings transcripts, reflection agent |
| 5 | Surface & reach | 2–3 wk | MCP server, Risk Engine V2, investor letter, dashboard v2 |

**If only three things get done:** the LLM gateway (P0-1), the LangGraph promotion
with the human-approval interrupt (P1-1–P1-3), and the calibration dashboard (P2-2).
Those move the project from "cool automation" to "this person engineers AI systems."

Task-level specs with inputs/outputs/acceptance criteria: see
[`.claude/TODO.md`](../.claude/TODO.md).

## 6. Blog/Article Series Candidates

1. "I let an LLM manage $1M (of fake money) — the architecture that keeps it honest"
2. "Migrating a 17-step pipeline to LangGraph: checkpoints, interrupts, and letting a human veto the AI"
3. "Your LLM app needs a gateway" — structured outputs, repair retries, routing, cost tracking
4. "Evals in CI: regression-testing prompts like code"
5. "Is my AI actually any good? Brier scores and calibration curves for an LLM fund manager"
6. "Bull vs. bear: making LLMs argue before they trade"
7. "RAG on SEC filings: what breaks when you parse 10-Ks at 2am"
8. "An MCP server for my AI hedge fund"
9. "Three weeks of an autonomous fund's mistakes, as told by its own memory"

## 7. Not Worth Building

- **Real brokerage integration / live money.** Compliance surface, real risk, zero
  additional engineering signal. The transparency angle works *because* it's simulated.
- **Fine-tuning / DPO for the decision model.** Dozens of decisions, not tens of
  thousands; no reliable reward signal (30-day noisy returns). If the fine-tuning
  checkbox matters, fine-tune a small local model on tweet/report style — one
  weekend, honest scope.
- **A full knowledge graph (Neo4j).** Metadata-filtered vector retrieval gets 90% of
  the value at 10% of the cost.
- **High-fidelity market microstructure** (order books, slippage models, intraday
  streaming). A quant-infra project, not an AI-engineering one. Flat slippage in the
  simulator is one line and sufficient.
- **Multi-user SaaS-ification** (auth, billing, tenants). Enormous effort, zero AI
  learning.
- **A React SPA dashboard.** Upgrade the dashboard only where it surfaces the AI
  work (traces, calibration, debates).
- **A hand-rolled agent framework.** LangGraph is the point.
- **Unscoped backtesting.** A naive "backtest the LLM" is quietly dishonest — the
  model's training data contains the historical outcomes (lookahead contamination).
  If built, build a *replay* harness for pipeline determinism and cached-decision
  regression testing, and say exactly that in the write-up.
