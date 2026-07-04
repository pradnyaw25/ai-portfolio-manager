# AI Portfolio Manager — Assessment & Roadmap V2 (July 2026)

A clean-slate re-evaluation after the v1 roadmap (`docs/ROADMAP.md`) was fully
executed: 32 merged PRs, ~7.7k src + ~4.6k test LOC, 256 tests, 23 days of live
data. This document supersedes v1 as the working plan. The actionable task list is
in [`.claude/TODO.md`](../.claude/TODO.md).

**Project goals (restated):** an impressive engineering-portfolio piece that
demonstrates modern AI-engineering skill and is credible in senior/staff interviews,
interesting enough to attract attention publicly, and possibly a future product.
Trading performance is secondary.

---

## 1. Audit — the honest verdict

**One-sentence summary: v1 built an exquisite laboratory and never ran the
experiment.** The control and assurance planes are genuinely strong; the
*intelligence* layer is one cheap model wearing six hats; and nothing yet
demonstrates that any of the AI machinery improves outcomes.

### Genuinely impressive
- **Assurance plane:** decision evals gating CI, deterministic scorers as the hard
  gate with an LLM judge as advisory (the correct hierarchy), a grounding check that
  blocks publication of ungrounded claims, Brier/calibration plumbing.
- **Control plane:** one LLM gateway (validation, repair-retry, backoff, routing,
  cost log); a deterministic risk layer the model can't argue past; system-origin
  trades; HITL gate; market-hours execution gating.
- **Operational maturity:** idempotent stores keyed by run_id, crash-resume that
  reuses the run_id, non-idempotent side effects guarded on resume, per-run cost. Two
  *real* production incidents root-caused and fixed (Qdrant payload-index 400 that
  silently disabled memory; a manual run trading at stale after-hours prices).
- **MCP server:** "ask Claude why the fund sold NVDA" — a novel demo for this genre.
- **Honest engineering writing** in the TODO (deviations, deferrals, tradeoffs).

### Superficial / commodity
- **Multi-agent is theater.** Every agent is `gpt-4o-mini` + a different prompt + the
  *same* context. No information asymmetry, no interaction (the bear never sees the
  bull), convictions cluster at 0.75–0.90, and there is no evidence it changes any
  decision.
- **"Model routing" routes gpt-4o-mini → gpt-4o-mini.** The seam is real; the routing
  is vestigial; fallback is same-provider.
- **The celebrated retrieval eval (0.15 → 1.00) is synthetic** — scenarios engineered
  so chunking wins. Demonstrates a mechanism, not production retrieval quality.
- **Trading substance is thin and the flagship metric is empty:** 23 days, +2%
  (meaningless), and **0 of 34 predictions resolved** — the calibration dashboard has
  nothing to show yet.
- **Ledger is CSV/JSONL** with read-all/rewrite-all "upserts"; the SQLite store is
  only for run progress. Caps every data-engineering claim.
- **256 tests, ~all against fakes.** Both live incidents slipped through because the
  integration seams (real Qdrant, real clock) were untested.

### The missing keystone
**No baseline, no ablation.** Nothing compares the fund to buy-and-hold SPY, to
random-from-watchlist, or to no-memory / no-debate / no-tools variants. Every
evaluator persona (staff engineer, VC, hiring manager, OSS maintainer) converges on
the same question — *does the AI machinery actually help?* — and today the answer is
"unknown." Also missing: any event-driven component, active alerting/drift
monitoring, and distribution basics (README hook, self-explaining landing page,
GitHub link from the site, demo video).

### What differentiates (double down)
Evals-gate-CI, the grounding gate, the incident write-ups, the MCP interrogation
demo, the reflection loop, and radical transparency as identity. **The
differentiators are all assurance and honesty features, not intelligence features —
that is the brand.**

---

## 2. Roadmap

Effort in focused hours. IDs (`V1-*`) are the working task list; specs in
`.claude/TODO.md`.

### Next 30 days — highest ROI
| ID | Item | Why | Effort |
|----|------|-----|--------|
| V1-1 | **Baseline + ablation harness** — fund vs SPY, random-from-watchlist, no-memory, no-debate, no-tools; results on the dashboard | Converts artifact → experiment; answers the only question everyone asks | 20–30h |
| V1-2 | **Strong-tier PM model + measured delta** — frontier model on PM/judges, cheap analysts; measure eval + quality delta vs cost | Kills "it's just 4o-mini" with data | 4–6h |
| V1-3 | **Presentation pass** — README hero + arch image + 90s demo GIF + MCP clip; landing page explains itself + GitHub link; hide empty calibration until populated | Distribution is the bottleneck | 8–10h |
| V1-4 | **Real-query retrieval eval** — 25–30 hand-labeled queries on the live corpus with real embeddings | Makes the RAG claim honest | 8–12h |
| V1-5 | **Debate that earns its keep** — information asymmetry per analyst + one rebuttal turn + disagreement metrics | Turns theater into an agent system; feeds V1-1 | 10–15h |

### Next 90 days — technical depth
| ID | Item | Why | Effort |
|----|------|-----|--------|
| V1-6 | **Replay harness** — record run inputs → deterministic replay → prompt-change regression on frozen days | Honest backtesting; CI on decisions, not just schemas | 30–40h |
| V1-7 | **SQLite/DuckDB system of record** — migrate ledger; decouple Pages exports; stop committing data to main | Closes repo-as-DB debt + 25-commit pollution | 15–20h |
| V1-8 | **Second real provider (Anthropic) + routing experiment** | Makes routing true; cross-provider eval is content | 10–15h |
| V1-9 | **Durable two-phase HITL** — decide→persist→approve→execute across restarts / from dashboard | Closes honest P1-3 deferral | 20–25h |
| V1-10 | **Intraday event reactor** — price-move triggers → cheap agent restricted to *proposing risk exits* | Introduces event-driven architecture with bounded authority | 25–35h |
| V1-11 | **Memory impact instrumentation** — which cited memories correlate with won predictions; decay/consolidation | Makes memory a measured system | ~15h |

### Next 6–12 months — standout ambition
| ID | Item | Why | Effort |
|----|------|-----|--------|
| V1-12 | **Multi-fund tournament** — N fund configs racing in public with a league table | **Flagship.** Fund → agent-experimentation platform in production; content writes itself | 60–100h |
| V1-13 | **Extract `decision-audit` OSS package** — grounding gate + citations + journal | The one asset with life beyond this repo | 40–60h |
| V1-14 | **Calibration-aware position sizing** — Kelly fraction scaled by measured confidence reliability | Closes the loop: the fund's own calibration changes its behavior | ~20h |
| V1-15 | **Streaming data plane + budgeted intraday agents** | Full event-driven story | 80h+ |

**Complexity / skills / interview value** for each item are tabulated in the audit
conversation; the short version: V1-1 and V1-6 are the highest staff-level signal,
V1-12 is the highest brand signal, V1-13 is the highest OSS signal.

---

## 3. Target Architecture (V2)

Three structural moves define V2; everything else already exists.

1. **Event log as spine** (SQLite/DuckDB-backed) — enables intraday reactors + replay.
2. **Real system of record + point-in-time replay store** — deterministic
   re-execution of any past run from its exact inputs.
3. **Fund-as-config** — makes ablations, baselines, and the tournament the *same*
   mechanism.

```
                    ┌────────────────────────────────────────────────┐
                    │            EXPERIMENT REGISTRY                 │
                    │  fund configs: model × memory × debate × risk  │
                    └───────────────────────┬────────────────────────┘
   MARKET EVENTS            ┌───────────────┼───────────────┐
┌──────────────┐    ┌───────▼─────┐  ┌──────▼──────┐  ┌─────▼───────┐
│ prices/news/ │    │  Fund A     │  │  Fund B     │  │  Baselines  │
│ filings feed │───▶│ (LangGraph  │  │ (ablated    │  │ SPY / random│
│ + EVENT LOG  │    │  subgraph)  │  │  variant)   │  │ (no LLM)    │
└──────┬───────┘    └───────┬─────┘  └──────┬──────┘  └─────┬───────┘
       │              ┌─────▼───────────────▼───────────────▼─────┐
       │              │       SHARED LLM GATEWAY (multi-provider,  │
       │              │       budgets, cost/latency, tracing)      │
       │              └─────┬──────────────────────────────────────┘
       │              ┌─────▼──────────────┐   ┌────────────────────┐
       │              │ DETERMINISTIC RISK │   │ ASSURANCE SERVICE  │
       │              │ + exec (per fund,  │──▶│ grounding · online │
       │              │ market-hours gated)│   │ evals · calibration│
       │              └─────┬──────────────┘   └─────────┬──────────┘
┌──────▼───────────────────▼──────────────────────────── ▼─────────┐
│  SYSTEM OF RECORD (SQLite/DuckDB): events, runs, trades,         │
│  decisions, predictions, memories-index  +  REPLAY STORE         │
│  (point-in-time inputs per run — deterministic re-execution)     │
└──────┬────────────────────────────────────────────────┬──────────┘
┌──────▼──────────┐  ┌──────────────┐  ┌────────────────▼──────────┐
│ Qdrant memory   │  │ Reflection    │  │ SURFACES: dashboard +     │
│ (decay/consol.) │  │ (weekly)      │  │ league table · MCP · X ·  │
└─────────────────┘  └──────────────┘  │ investor letter           │
                                        └───────────────────────────┘
```

**How far can it go?** As a *fund*: nowhere, by design. As an *agent-experimentation
platform operating in public with full auditability*: genuinely far. Adopt that
framing everywhere — "my bot trades stocks" is a graveyard genre.

---

## 4. Launch Readiness

- **Name: rename.** "AI Portfolio Manager" is unsearchable/unownable and pattern-
  matches to the meme category. Candidates (verify availability): **Glasshouse**
  (`glasshouse.fund`, transparency = brand — top pick), PaperTrail (collision risk:
  SolarWinds Papertrail), Candor Capital. Low-effort fallback: keep the name + the
  tagline *"the AI fund that shows its work."* The tagline matters more than the name.
- **Domain:** buy the `.com` (~$10) + `.fund` (~$50/yr) of the chosen name. Skip `.ai`
  unless pivoting to the platform framing.
- **Landing page** (current one fails cold visitors): hero = live value + one-sentence
  what-it-is + GitHub/X buttons → three proof tiles (calibration, decision journal,
  cost/decision) → how-it-works (arch diagram) → **"Interrogate the fund"** MCP demo →
  latest investor letter → disclaimer.
- **Demos (priority order):** (1) 20s MCP GIF — *"why did the fund sell NVDA?"* → sourced
  answer; (2) 90s dashboard→journal→debate→grounding recording; (3) calibration curve
  *once predictions resolve*; (4) daily-run terminal GIF with cost line.
- **GitHub:** hero image + badges + 3-line pitch above the fold; keyless `make demo`
  (replay a canned day); architecture image inline; MCP section; CONTRIBUTING; repo
  topics; social-preview image; **stop committing daily data to main**.

**Launch checklist by impact.**
- **P0 (before promotion):** landing page self-explains + GitHub link · README
  hero/pitch/GIF · MCP demo GIF · stop data commits · first resolved predictions
  visible (or hide the empty calibration module).
- **P1 (launch week):** name/domain · `make demo` · Article 1 · pinned X thread ·
  social-preview images.
- **P2 (after):** CONTRIBUTING · dashboard views for risk_events + investor letter
  (data exists, no UI) · social-proof collection.

---

## 5. Content Strategy

- **Article 1 — "Inside an AI Fund That Has to Show Its Work"** (architecture deep-
  dive; senior/staff audience). Control → decision (honestly: v1 debate was theater) →
  assurance (evals gating CI, grounding, calibration) → ops → what I'd delete.
  Diagrams already on the architecture page. Promote: Show HN, X, r/MachineLearning,
  LangGraph community.
- **Article 2 — "Three LLMs Walk Into an Investment Committee"** (agent layer;
  engineers building agents). The conviction-clustering *failure* → information
  asymmetry as the fix → measured before/after. **Requires V1-5 first** — the
  failure→fix arc is the article.
- **Article 3 — "Everything That Broke Running an Autonomous AI Fund"** (ops retro;
  most shareable). Qdrant 400 silently killing memory → after-hours stale-price trade →
  repair-retries in prod → tweet double-post-on-resume → what $0.01/decision buys.
  HN loves honest failure posts.
- **Retrospective (2–3 months post-launch) — "What 34 Predictions and 4 Ablations
  Taught Me About My Own AI."** Resolved predictions + Brier trend, fund vs baselines +
  ablations (**requires V1-1** — schedule content after evidence), agent-failure
  taxonomy, architecture changes, "was the debate worth the tokens." The piece that
  separates this from every abandoned GPT-trader repo.
- **Cadence:** keep automated daily tweets as wallpaper; add a weekly investor-letter
  thread (already generated) and one build-in-public post per shipped item, always
  with a chart/screenshot.

---

## 6. Brutal Prioritization

- **20h:** presentation pass (10h) + strong-model PM delta (4h) + quick fund-vs-SPY
  chart (6h). → findable, demoable, one number that answers "does it work?"
- **50h:** + full ablation harness (V1-1) + Article 1. → experiment run, flagship
  article live.
- **100h:** + debate asymmetry (V1-5) + Article 3 + real-query retrieval eval (V1-4) +
  SQLite ledger (V1-7) + name/domain/landing. → every audit criticism answered.
- **250h:** + replay harness (V1-6) + **tournament MVP, 3 funds + league table
  (V1-12)** + Anthropic provider (V1-8) + retro article + start OSS extraction (V1-13).
  → an agent-experimentation platform in production.

**ROI ranking:** baselines/ablations · presentation · Article 3 · strong-model delta ·
Article 1 · debate asymmetry · tournament · replay · real-query eval · SQLite ledger ·
rename · OSS extraction · two-phase HITL · intraday reactor · rest.

**Assumption challenges.**
1. Marginal ROI on *features* is now negative; on *evidence and writing* it's enormous.
   Next 100h ≈ 40% evidence / 30% content / 20% presentation / 10% code.
2. The fund is the demo, not the project. Durable framing: *"controlled agent
   experiments in production, in public, with full audit trails"* — the tournament
   makes it literal.
3. Most valuable alternative direction: the **OSS `decision-audit` extraction**. A used
   library beats a watched fund for personal brand; the fund becomes its reference
   deployment.
4. Don't chase real-money product (compliance, untestable returns) — v1's rejection of
   "portfolio copilot" still holds. The only product-shaped opportunity is
   agent-auditing infrastructure, discovered via the OSS route.
5. **Scheduling constraint:** predictions resolve on 30-day horizons; the first cohort
   matures ~1 week out. Sequence the launch so the calibration dashboard is *populated*
   when traffic arrives — launching with the headline metric reading "no data" would
   undercut the transparency brand.

---

## 7. Superseded / carried forward from v1

- v1's parked list (`docs/ROADMAP.md` §7) still holds: no live brokerage, no
  fine-tuning, no knowledge graph, no market-microstructure sim, no SaaS-ification, no
  React SPA, no hand-rolled agent framework, no naive backtest.
- v1 P5-4 (replay backtester) is **promoted and reframed** as V1-6 (replay harness for
  determinism + decision regression, not "would the LLM have won").
