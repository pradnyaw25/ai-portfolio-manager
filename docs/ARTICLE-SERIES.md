# Article Series — the publishing plan

> Planned 2026-08-09. Supersedes the ordering in [`ROADMAP-V2.md`](ROADMAP-V2.md) §5,
> which led with the architecture deep-dive. It now leads with calibration, per the
> "Reposition the launch around calibration" decision in `CLAUDE.md`.

**Related docs.** [`article-notes.md`](article-notes.md) is the raw material — findings
captured while fresh. [`incidents.md`](incidents.md) is the failure log. This file is the
*plan*: what gets published, in what order, on what evidence, and what has to ship first.
When a finding lands, append it to `article-notes.md`; when it changes what gets
published, update this file.

## The spine

The fund is an instrument. Each article is one reading off it. Every piece must have:

1. **One falsifiable claim** — something that could have come out the other way.
2. **One dataset already on disk** — no article waits on data that does not exist yet.
3. **One method worth stealing** — the reusable technique is what engineers share.

What the series is *not*: "here is my AI fund." That genre is crowded, its implicit
claim ("I beat the market") is not believed, and the fund's returns are the least
interesting thing about it.

## Sequence at a glance

| # | Piece | Evidence | Gate | Status |
|---|---|---|---|---|
| 1 | I upgraded the model and the calibration got worse — scoring 483 LLM predictions | on disk | none | drafting |
| 2 | Everything that broke — ops retro | on disk | none | not started |
| 3 | Your agent's biases hide in its plumbing | on disk | memory-prefix fix must ship | blocked |
| 4 | Three LLMs walk into an investment committee | on disk | none | not started |
| 5 | Whose confidence is honest? — multi-model bake-off | needs ~4 weeks live | multi-model calibration build | blocked |
| 6 | Inside a fund that has to show its work — architecture + MCP | on disk | deliberately last | not started |
| 7 | Retrospective | needs ~3 months | N roughly doubles | blocked |

**Rhythm.** 1 and 2 are the launch, roughly a week apart, so the second lands while the
first is still circulating. 3 and 4 keep the month alive. 5 lands about four weeks after
the multi-model build. 6 goes out once traffic exists to convert. 7 at roughly three
months.

---

## 1. "I upgraded the model and the calibration got worse" — scoring 483 LLM stock predictions

**Publish first. This is the launch.** *(Retitled 2026-10-02; the August draft was "The
confidence was a lie" at N=177. The extra N changed the story — see below.)*

- **Hook.** Every LLM app ships confidence scores. Almost nobody scores them. I made one
  say "0.7" hundreds of times, with dates and receipts, graded every call against SPY —
  then swapped in a newer, pricier model halfway through and watched the curve get worse.
- **Claim.** Stated confidence carries no information above 0.6, the newer model is *less*
  calibrated than the cheap one it replaced, and neither ever beat a constant answer on
  its own window. The one flattering finding at N=177 was a regime artifact.
- **Evidence on disk** (`data/predictions.jsonl`, as of 2026-10-02; scorer is
  `src/scoring/prediction_scorer.py`, metrics in `src/scoring/calibration.py`):
  - 551 predictions, 483 scored, 68 open. 247 correct = **51.1% hit rate**, over
    2026-07-13 to 2026-10-02. **Brier 0.2686** — a coin flip scores 0.25.

    | model | window | n | hit | Brier | best constant call |
    |---|---|---|---|---|---|
    | gpt-4.1-mini | 07-08 → 08-07 | 237 | 55.7% | 0.2550 | 59.1% (always underperform) |
    | gpt-5.6-terra | 08-10 → 09-21 | 239 | 46.4% | 0.2815 | 52.3% |

    terra's 0.6–0.7 bucket: **37.4% on 91 calls** at a stated ~65%. Aggregate buckets:
    0.5–0.6 → 54% (n=177), 0.6–0.7 → 47% (n=205), 0.7–0.8 → 55% (n=93), 0.8–0.9 → 38% (n=8).
  - **The buried lede, revised.** At N=177 the story was "UNDERPERFORM calls hit 67%,
    OUTPERFORM 44% — it spots laggards." At N=483: 59% of names lagged SPY in July and the
    model mostly said underperform. Always saying underperform would have beaten it. When the
    base rate flipped to 52% under terra, the laggard edge vanished (44.5%). *Say this
    plainly — the retraction is the most credible paragraph in the piece.*
- **Method worth stealing.**
  - **Publish the constant-call baseline next to the hit rate.** A directional hit rate
    is meaningless against 50%; it has to beat "always say the majority outcome" for its
    own window. The page does this now (`constant_call` in `predictions.json`).
  - **Tag every prediction with the model that made it.** #113 did; without it the model
    swap would be an invisible kink in one aggregate curve. Split curves per model.
  - **Audit the sampler, not just the metric.** v1 spawned predictions only from executed
    BUYs — about 7 in a month, every one a name that had cleared every risk gate.
    Decoupling predictions from trades is the fix.
  - **Non-overlapping windows; short horizons buy independent samples fast.** One open
    prediction per (symbol, horizon); 5d windows are why a curve existed three weeks in.
- **What to cut.** The 0.8–0.9 bucket alone (n=8). The "traded-only vs all views"
  two-curve plan: `became_trade` is true for **3** scored calls. Say plainly why it is not
  viable rather than dropping it silently.
- **Honest scope to state up front.** Paper trading. Two models in *sequence*, not
  side-by-side — the windows don't overlap, so regime is a confound. That is exactly why
  piece 5 (same-day multi-model) exists. Directional, not a benchmark.
- **Artifact.** The calibration chart with one dashed curve per model, the base-rate line,
  and the live page so a reader can check the claim against dated receipts.
- **Venue.** Show HN, X, r/MachineLearning. Lead with "upgraded the model, calibration got
  worse" — it is the line people will repeat.

## 2. "Everything that broke" — the ops retro

- **Hook.** Nine production failures in an autonomous fund, and the thing they have in
  common is that every single one looked like success while it was happening.
- **Claim.** In an autonomous system the dangerous failure mode is not the crash. It is
  the silent degradation that still writes a report, still passes CI, still tweets.
- **Evidence on disk.** [`incidents.md`](incidents.md) — nine written-up incidents plus
  four earlier stubs. The through-line orders itself:
  - A late cron and a shared concurrency group cost a whole trading day (2026-08-06).
  - The fund timed out mid-decision and **CI reported success** (2026-08-05).
  - The risk engine logged 22 "rejected trades" that were never trades (2026-07-09).
  - No LLM client timeout — the SDK default is 600s, so one stalled call froze a batch
    for ten minutes with the process alive and no log line (2026-07-08).
  - A "dry run" that was not: a test tweet went live (2026-07-06).
  - The grounding gate muzzled the fund over a rounding error (2026-07-06).
  - Qdrant payload-index 400 silently disabled memory (expand the stub before writing).
- **Method worth stealing.** A per-call append-only log (`data/llm_calls.jsonl`) is the
  cheapest liveness probe there is: a live process writing zero rows is blocked, not
  slow. Buffered stdout tells you nothing. More generally: assert on *evidence of work
  done*, not on exit codes.
- **Why second.** It is the most shareable format on HN, and it buys the credibility that
  makes piece 1's numbers believable. Publishing your own failure log is the strongest
  available signal that the calibration numbers were not curated.

## 3. "Your agent's biases hide in its plumbing"

**Blocked on:** shipping the memory-prefix fix (backlog: "Memory retrieval reaches only
the alphabetically-early names"). The failure → fix → measured-change arc *is* the piece.

- **Hook.** The About page advertises a 33-name AI-compute universe. The fund traded the
  same boring mega-caps for months. Neither the prompt nor the universe was at fault —
  two lines of plumbing were.
- **Claim.** Agent bias does not live in the prompt. It lives in how scarce context is
  allocated, and it is invisible in every run's output because it shows up only as an
  absence.
- **Evidence on disk.**
  - **News followed ownership.** Per-symbol news was fetched for held positions only
    (`held_symbols[:8]`), so a watchlist-only name arrived with a price and a return and
    **no catalyst** — nothing for the bull analyst to build a case from. Fixed via
    `WATCHLIST_NEWS_LIMIT` in `src/research/market_context.py`.
  - **Memory retrieval was alphabetical.** `extract_memory_symbols` (`src/main.py:142`)
    takes `research["symbols"][:12]` off a **sorted** list, so the slice is an
    alphabetical prefix. 13 of the 34 universe names are unreachable by memory, and all
    13 are unheld. Holdings are guaranteed inclusion; everything else plays a lottery on
    its ticker.
  - **The honest confound.** The AI-infra names were in 20–34% 30-day drawdowns
    (CRWV −28%, IREN −34%, APLD −30%). A momentum-tilted committee correctly avoids
    falling knives. The plumbing fix lets the universe be *considered*; it does not and
    should not force trades. Say this, or a reader will say it for you.
- **Method worth stealing.** Audit what your agent *never* does, not only what it does.
  Then check whether a resource-allocation rule ("fetch news for holdings") is quietly
  encoding the bias you are trying to explain away as model behavior.
- **What makes it land.** Two bugs, found independently, months apart, both with the same
  shape: scarce context went to incumbents and the portfolio self-reinforced.

## 4. "Three LLMs walk into an investment committee"

- **Hook.** I had a bull, a bear and a risk analyst arguing before every trade. It looked
  sophisticated. It was theater: three copies of the same cheap model, fed the same
  context, that never talked to each other.
- **Claim.** Multi-agent debate collapses into agreement because the *inputs* are
  identical, not because the models are too weak. Asymmetry beats a bigger model.
- **Evidence on disk.**
  - The three fixes: information asymmetry (bull sees momentum + news, bear sees downside
    + cautionary memory, risk sees a computed exposure block), a rebuttal turn where the
    bear reads the bull's actual case, and `conviction_spread` as a recorded metric.
  - Before: convictions clustered 0.75–0.90. After, on the mixed-signal NVDA case: bull
    0.70 / bear 0.80 / risk 0.90, spread 0.20, each citing different evidence.
  - **The ablation receipt** (`scripts/compare_ablations.py`, fixed gpt-4o judge, N=8):
    full **4.13**, no-memory **3.58 (−0.54)**, no-debate **3.88 (−0.25)**. Removing debate
    also dropped structural pass_rate 1.0 → 0.625.
  - **The credibility move.** The effect is *localized*. Killing memory dropped the five
    memory-dependent scenarios (risk_flag 4.33 → 2.67, loss_lesson 4.0 → 3.0) while the
    three debate scenarios stayed **identical at 4.333**. If the ablation leaked a general
    "less context scores lower" bias, those would have moved. They did not.
- **Method worth stealing.** To test whether a component earns its keep, ablate it against
  a **fixed** grader and read the *per-item* deltas. The mean tells you whether it helped;
  the per-item pattern tells you whether you measured the component or an artifact.
- **Scope.** Reasoning quality on an eval set at N=8, not live P&L. The tools ablation is
  not measurable this way — eval scenarios carry research as a fixed input.

## 5. "Whose confidence is honest?" — the multi-model bake-off

**Blocked on:** the "Multi-model live calibration" build, then roughly four weeks of live
calls. #113 already tags each prediction with the model that made it, so what remains is a
per-model call inside `record_market_calls` and one published curve per model.

- **Hook.** Piece 1 scored one model. This scores several against each other on the same
  prompt, the same day, the same market, with dated public receipts.
- **Claim.** Stated confidence is a model-specific property, and the ranking by
  calibration need not match the ranking by benchmark or by price.
- **Evidence.** Live per-model curves once they accumulate, plus the offline eval history
  that motivated it (`docs/model-selection.md`): on the 8 golden scenarios with the judge
  held fixed, gpt-4o cost about 11× gpt-4o-mini and scored *lower* (3.42 vs 3.58);
  gpt-4.1 led by +0.25/5, inside the judge's own noise, for the same 11×. The 2026-08-08
  re-run moved both tiers to gpt-5.6 (luna 4.04/4.17 at $0.00162, terra 4.08/4.21 at
  $0.01421).
- **Method worth stealing.** Fixed-judge A/B — hold the judge constant and vary only the
  thing under test, or upgrading the model silently upgrades the grader. And separate the
  gate from the grade: deterministic gates saturate (every model passed 8/8), so only a
  graded rubric can show a delta.
- **Scope guard.** Spend on the comparison *across* models, not on making the single fund
  smarter. `make eval-compare` already showed bigger models do not move decision quality
  on this eval set.

## 6. "Inside a fund that has to show its work" — architecture + MCP

**Deliberately last.** Weakest standalone hook, strongest conversion piece once readers
arrive from 1 through 3.

- **Hook.** Not the architecture. The **read-only MCP server**: point Claude at a real
  fund's decision history and interrogate it. Currently buried as README bullet 11.
- **Claim.** An agent system is only auditable if every decision leaves a durable,
  addressable artifact. Here is what that costs to build and what it buys.
- **Evidence.** The 22-node LangGraph cycle, deterministic risk guardrails that override
  the LLM, the decision journal as audit trail, prerendered per-day decision pages
  (crawlable text went from 281 chars to a median of 1,975), evals gating CI, and the
  grounding gate. Diagrams already exist on the architecture page.
- **Honest section, kept from the roadmap.** "What I would delete." The piece is more
  credible for naming the machinery that did not earn its place.

## 7. Retrospective — "What N predictions and 4 ablations taught me about my own AI"

Roughly three months post-launch, when scored N has roughly doubled and the Brier trend
has a shape. Resolved predictions over time, fund vs baselines vs ablations, an
agent-failure taxonomy, architecture changes made in response to evidence, and a straight
answer on whether the debate was worth the tokens. This is the piece that separates the
project from every abandoned GPT-trader repo — it requires only that the fund keeps
running and keeps being scored.

---

## Build work this plan depends on

Only two items gate anything. Everything for pieces 1, 2, 4 and 6 is already on disk.

1. **Memory-prefix fix** — gates piece 3. `extract_memory_symbols` slices a sorted list;
   13 of 34 universe names can never be retrieved. Small fix; the article needs the
   before/after.
2. **Multi-model live calibration** — gates piece 5. Per-model call in
   `record_market_calls`, one curve per model on the site. Then wait about four weeks.

## Standing rules for every piece

- **Receipts over claims.** Every number links to the decision page, prediction, or
  incident it came from.
- **State the scope before a reader does.** Paper trading, small N, one market regime.
  Volunteering the limitation is what makes the rest believable.
- **Publish the null results.** A bucket that came out flat, a component that did not
  help, a plan abandoned for lack of N — all of it is content, and it is the differentiator.
- **Never quote the best number as the typical one.** The 7,300-char decision page is the
  best page, not the median (1,975). The same discipline applies to every metric here.
