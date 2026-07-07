# Article Notes — build-in-public findings

Raw material for write-ups. Where `docs/incidents.md` collects things that *broke*,
this collects engineering *findings* worth an article or a build-in-public post —
each captured while it's fresh, with the hook, the numbers, the reusable method, and
which planned piece it feeds (see `docs/ROADMAP-V2.md` §5).

Entry template:
- **Date · working title**
- **Hook** — the one-line tension that makes someone read
- **The finding** — what actually happened, with numbers
- **Method worth stealing** — the reusable technique (this is what engineers share)
- **Why it's shareable** — the angle
- **Feeds** — which article / post

---

## 2026-07-07 · "I let a frontier model run my AI fund — the data said don't"

- **Hook.** The reflex is to reach for the biggest model for the *important*
  decisions. I built a harness to measure whether that's true for my fund's
  portfolio-manager decisions. The flagship cost **~11× more for no reliable gain** —
  and actually scored *lower* than the cheap model in one run.

- **The finding.** Same 8 golden decision-eval scenarios, same prompt, temp 0, only
  the "strong"-tier model varied (analysts held on the cheap tier). A single fixed
  LLM judge graded every candidate on a 1–5 rubric (reasoning / specificity /
  risk-awareness), so the score isolates the decision-maker, not the grader.

  | model | pass | quality/5 | $/decision | vs. cheapest |
  |-------|------|-----------|------------|--------------|
  | gpt-4o-mini | 100% | 3.58 | $0.00047 | 1× |
  | **gpt-4.1-mini** | 100% | **3.75** | $0.00095 | ~2× |
  | gpt-4o | 100% | 3.42 | $0.0053 | ~11× |
  | gpt-4.1 | 100% | 3.83 | $0.0054 | ~11× |

  Three things fell out of it:
  1. **The structural floor is model-independent.** Every model passed 8/8 on the
     deterministic gates (schema, risk compliance, citations). A cheap model already
     produces well-formed, rule-compliant, correctly-cited decisions. Pass-rate can't
     separate models — you *have* to grade substance to see any difference.
  2. **The flagship is dominated.** `gpt-4o` was 11× the cost for zero quality gain.
     `gpt-4.1` led by only +0.25/5 — inside the judge's own noise — for 11× the cost.
  3. **The sweet spot was the *mini* of the newer generation** (`gpt-4.1-mini`):
     near-flagship quality at ~2× the cheapest model's cost. That's now the fund's
     strong tier; the cheap tier stays `gpt-4o-mini`.

- **Method worth stealing.**
  - **Fixed-judge A/B.** To compare decision-makers with an LLM judge, hold the judge
    model constant and vary only the thing under test. Otherwise "upgrade the model"
    silently upgrades the grader too and you measure nothing.
  - **Separate the gate from the grade.** Deterministic pass/fail gates saturate — a
    cheap model clears them. A *graded* rubric is what reveals (or fails to reveal) a
    quality delta.
  - **Report the noisy axis next to the un-noisy one.** LLM-judge scores wobble ~±0.3
    even at temp 0 (models aren't deterministic), so a +0.08–0.25/5 "win" is nothing.
    Cost deltas *aren't* noisy — put them side by side and the decision makes itself.
  - **Config-as-experiment.** The whole comparison is one env knob (`LLM_STRONG_MODEL`)
    swept over candidates — the same seam that will drive the fund-vs-fund ablations.

- **Why it's shareable.** Contrarian to the "always use the best model" reflex, with
  concrete numbers and a reusable harness. Anti-hype; on-brand for "measure, don't
  guess." The punchline — *the cheap model already passes every gate; the frontier
  model buys you noise at 11× the price* — is the kind of counterintuitive result HN
  and eng-Twitter reward.

- **Caveats to keep (honesty is the brand).** n=8, single run, one LLM-judge rubric —
  directional, not a benchmark. Re-runnable with `make eval-compare` as the eval set
  hardens or new models ship.

- **Feeds.** Article 1 (architecture/assurance — "every decision justified by data,
  including which model makes it"), or a standalone "Measure, Don't Guess: Picking the
  Model for an AI Agent" post. Also a data point for the retrospective. Source of
  truth for the decision itself: `docs/model-selection.md`; harness:
  `scripts/compare_strong_model.py`.
