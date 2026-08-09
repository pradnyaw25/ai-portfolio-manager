# Strong-tier model selection (measured)

The LLM gateway routes calls by **tier**: a *strong* tier (portfolio-manager
synthesis, the grounding/decision judges, rebalance checker, reflection, investor
letter) and a *cheap* tier (bull/bear/risk analysts, research summaries, tweets).
For a long time both tiers resolved to `gpt-4o-mini` — so "strong" routing was
vestigial and every agent was the same cheap model in a different hat.

This note records the **measured** decision for what the strong tier should be,
per roadmap item V1-2. The harness is committed (`make eval-compare`,
`scripts/compare_strong_model.py`) so the decision can be re-run as scenarios and
models evolve.

## Method

For each candidate strong-tier model, run the 8 golden decision-eval scenarios
through the portfolio manager (analysts held on the cheap tier), at
`temperature=0`, holding prompt and scenarios constant, and measure:

- **pass_rate** — the deterministic scorers (schema, risk compliance, citation
  validity, debate completeness). Structural correctness, judge-free.
- **quality/5** — an LLM rubric (`src/scoring/decision_quality.py`) scoring
  reasoning, specificity, and risk-awareness 1–5. To isolate the *decision-maker*,
  the judge model is held **constant** (`gpt-4o`) while only the PM model varies.
- **cost / latency** — from the gateway's per-call log, isolated per candidate by
  `run_id`.

## Result (2026-07-07, judge = gpt-4o, 8 scenarios, temp 0)

| model          | pass | quality/5 | $/scenario | vs. mini cost |
|----------------|------|-----------|------------|---------------|
| gpt-4o-mini    | 100% | 3.58      | $0.00047   | 1×            |
| **gpt-4.1-mini** | 100% | **3.75**  | $0.00095   | ~2×           |
| gpt-4o         | 100% | 3.42      | $0.00534   | ~11×          |
| gpt-4.1        | 100% | 3.83      | $0.00536   | ~11×          |

## Findings

1. **The structural floor is model-independent.** Every candidate passes 8/8
   deterministic scorers — a cheap model already produces well-formed,
   risk-compliant, correctly-cited decisions. Pass-rate does not separate models.
2. **`gpt-4o` is dominated.** ~11× the cost of `gpt-4o-mini` for *no* quality gain
   (it scored lower here). There is no reason to route the strong tier to it.
3. **The flagship isn't worth it.** `gpt-4.1` scored highest (3.83) but only
   ~+0.25/5 over `gpt-4o-mini` — inside the judge's run-to-run noise (repeated runs
   moved a fixed model's score by ~±0.3 even at temp 0, since the models aren't
   perfectly deterministic) — for ~11× the cost.
4. **`gpt-4.1-mini` is the sweet spot.** Second-highest quality (3.75, statistically
   indistinguishable from the flagship at this sample size) at ~2× `gpt-4o-mini`'s
   cost and ~5.6× cheaper than the frontier.

## Decision

**Default the strong tier to `gpt-4.1-mini`; keep the cheap tier on `gpt-4o-mini`.**

- It's a genuine generational upgrade over the cheap model, so the "strong" route is
  no longer vestigial — PM, judges, rebalance, reflection, and the investor letter
  now run a distinct, stronger model.
- It's **cost-safe**: <$0.001/decision, ~pennies/day at the fund's call volume.
- It rejects the flagship *on the evidence*, not on vibes — the whole point.
- Bonus: it upgrades the grounding judge, which `gpt-4o-mini` handled unreliably (see
  the 2026-07-06 grounding-gate incident in `docs/incidents.md`).

Overrides remain available via `LLM_STRONG_MODEL` / `LLM_CHEAP_MODEL` (e.g. a
per-fund config in a future ablation/tournament can dial the strong model up or
down and this same harness measures the delta).

### Caveats / honest limits

- n = 8 golden scenarios, single run, one LLM judge — directional, not a benchmark.
  The rubric deltas are within judge noise; the *cost* deltas are not.
- The judge is itself an LLM (`gpt-4o`); a fixed judge makes the comparison fair but
  not absolute.
- Re-run with `make eval-compare` (optionally `--candidates ... --judge ...`) when
  the eval set gets harder or new models ship.

---

## Re-run (2026-08-08, judge = gpt-4o, 8 scenarios) — gpt-5.6 family

OpenAI's gpt-5.6 family (`sol` flagship, `terra` strong-at-lower-price, `luna`
high-volume) prompted a re-measurement with the same harness.

| model | pass | quality/5 (run 1 / run 2) | $/scenario | ms/scenario |
|---|---|---|---|---|
| gpt-4.1-mini *(incumbent)* | 100% | 3.79 / 3.71 | $0.00173 | 12,188 |
| **gpt-5.6-luna** | 100% | **4.04 / 4.17** | **$0.00162** | **9,960** |
| gpt-5.6-terra | 100% | 4.08 / 4.21 | $0.01421 | 11,354 |

Published pricing per 1M tokens: luna $0.20/$1.20, terra $2/$12, sol $5/$30,
against gpt-4.1-mini's $0.40/$1.60.

### Decision

**Move both tiers to `gpt-5.6-luna`.**

Unusually, there was no trade-off to weigh. Luna scored ~0.36/5 higher than the
incumbent averaged across two runs, at **93% of the cost** and **82% of the latency**.
Better, cheaper, faster.

`gpt-5.6-terra` scored marginally higher again (+0.04 over luna) but costs **8.2×**
per scenario. That is the same verdict the 2026-07-07 run reached about the flagship,
for the same reason: the gap is inside the judge's noise and the price is not.

### Honest limits

- **n = 8 scenarios, two runs.** The *ordering* (terra > luna > gpt-4.1-mini) held in
  both, which is the load-bearing part. The absolute numbers moved ±0.13 between runs.
- **Temperature could not be held constant.** The gpt-5.6 family rejects
  `temperature=0` (HTTP 400, "only the default (1)"), so the new models were measured
  at temperature 1 while gpt-4.1-mini ran at 0. The new models were therefore judged
  under *more* randomness and still scored higher, which if anything understates them
   — but this is no longer a like-for-like comparison, and the harness's "temp 0 for
  determinism" premise no longer holds across model generations.
- **`reasoning_effort` was left at its default.** The gpt-5.6 models accept
  none/low/medium/high/xhigh/max. It was not set, so it is an uncontrolled variable
  and a tuning lever that has not been explored.
- **Both tiers now resolve to the same model**, which makes the strong/cheap split
  vestigial again — the exact condition this document was originally written to end.
  It is deliberate for now; `LLM_STRONG_MODEL=gpt-5.6-terra` restores a real split.
