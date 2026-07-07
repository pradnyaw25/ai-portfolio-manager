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
