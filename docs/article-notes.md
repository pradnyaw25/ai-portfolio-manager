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

---

## 2026-07-07 · "My multi-agent debate was theater — here's what made it real"

- **Hook.** I had a bull, a bear, and a risk "analyst" arguing before every trade.
  It looked sophisticated. It was theater: three copies of the same cheap model, fed
  the *same context*, that never talked to each other — so their convictions clustered
  at 0.75–0.90 and the "debate" changed nothing.

- **The finding.** Three targeted changes turned parallel monologues into a debate:
  1. **Information asymmetry** — each analyst now argues from a *different slice* of the
     context. Bull sees momentum + news; bear sees downside signals + cautionary memory
     (past risk lessons, mistakes); risk sees a *computed* exposure block (position +
     sector concentration, cash). Same models, different evidence.
  2. **A rebuttal turn** — the bear reads the bull's actual case and responds to it,
     updating its conviction. Interaction, not three isolated takes.
  3. **A disagreement metric** — `conviction_spread` (max−min across analysts), recorded
     per debate, so "did they actually disagree?" is a number, not a vibe.
  On the mixed-signal test case (NVDA, up short-term but fading on 30d) the analysts
  landed at bull 0.70 / bear 0.80 / risk 0.90 (spread 0.20) — each citing *different*
  evidence: the bull on chip-demand momentum, the bear on the 30-day fade, the risk
  analyst on "100% concentrated in one name and sector." The clustering broke because
  the *inputs* stopped being identical.

- **Method worth stealing.**
  - **Asymmetry beats bigger models for multi-agent.** The cheap fix wasn't a smarter
    model — it was giving each agent a genuinely different view. Identical context is
    why "debates" collapse into agreement.
  - **Make disagreement observable.** A one-number spread metric turns "is the committee
    doing anything?" into something you can chart and gate on.
  - **Interaction, not just aggregation.** One rebuttal turn (agent B sees agent A) is a
    disproportionate upgrade over N parallel calls a synthesizer merges.
  - **Config-as-experiment.** An `ENABLE_DEBATE` flag lets a later ablation measure
    debate-vs-no-debate on the same days — the honest test of whether it's worth the tokens.

- **Why it's shareable.** Everyone building agent committees hits the "they all agree"
  problem. The failure→fix arc (theater → asymmetry + rebuttal + a disagreement metric)
  is concrete, reusable, and honest about the first version being fake sophistication.

- **Feeds.** Article 2 — "Three LLMs Walk Into an Investment Committee" (the roadmap's
  planned agent-layer piece; the conviction-clustering failure IS the article). Code:
  `src/agents/analysts.py`, `src/agents/debate.py`.

---

## 2026-07-07 · "My AI fund had a 33-name universe and only ever traded 19 of them"

- **Hook.** The About page proudly lists a 33-name, AI-compute-thesis universe
  (semis, neoclouds, data-center power). In months of trading it had touched maybe 19
  of them — always the boring mega-caps (AAPL, NVDA, MSFT…), never the AI-infra names
  it was supposedly built around. Someone asked why. The answer was one line of code.

- **The finding.** It wasn't a data or universe bug — the watchlist matched the site
  exactly, and the market-context builder fed all 33 names to the portfolio manager
  daily *with live prices and returns*. Two things quietly starved the unowned names:
  1. **News followed ownership, not signal.** Per-symbol news was fetched only for
     *held* positions (`held_symbols[:8]`). Watchlist-only names arrived with a price
     and a return but **no catalyst** — so the bull analyst (which argues from
     "momentum, relative strength, catalysts") had nothing to build a case on, and no
     new position ever got initiated.
  2. **Their momentum was genuinely awful.** The AI-infra names were in 20–34% 30-day
     drawdowns (CRWV −28%, IREN −34%, APLD −30%). A momentum-tilted committee correctly
     avoids falling knives — so even the names it *did* see, it (rightly) skipped.
  Net: an aspirational universe that, in practice, churned the same ~19 stable names.

- **The fix.** Make news follow **signal**: fetch per-symbol news for held names **plus
  the biggest-moving unheld watchlist names**, so the analysts get catalysts for
  candidates, not just incumbents. One bounded change to the context builder
  (`WATCHLIST_NEWS_LIMIT`). It doesn't *force* trades — the drawdown reality still means
  it won't buy falling knives — it just lets the universe actually be considered.

- **Method worth stealing.**
  - **Audit what the agent never does, not just what it does.** The bug was invisible in
    every run's output — it showed up only as an *absence* (names that never appeared).
  - **Resource allocation encodes bias.** "Fetch news for holdings" quietly made the
    portfolio self-reinforcing: you can only build a case for a name you already own.
    Give scarce context (news, tools, tokens) to *candidates*, not just incumbents.

- **Why it's shareable.** The gap between the impressive-looking universe and the timid
  reality is relatable and a little funny, and the root cause (news = ownership) is a
  subtle, generalizable agent-design trap. Honest, concrete, one-line fix.

- **Feeds.** Article 3 (ops/behavior retro) or a standalone "your agent's biases hide in
  its plumbing" post; also a retrospective data point once the AI-infra names actually
  start getting evaluated. Code: `src/research/market_context.py`.
