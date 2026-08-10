# Incident Log — "Everything That Broke Running an Autonomous AI Fund"

A running log of production incidents and their root causes. Source material for
the ops-retro article (ROADMAP-V2 §5, Article 3) and build-in-public posts. Append
a new entry each time something breaks; keep the *honest* detail (symptom → root
cause → fix → what let it through) — the honesty is the point.

Entry template:
- **Date · one-line title**
- **Symptom** — what was observed
- **Root cause** — the real reason
- **Fix** — what changed (link PR/commit)
- **Detection gap** — why it wasn't caught earlier
- **Article angle** — the lesson worth writing about

---

## 2026-08-10 · A model upgrade broke tool calling, and an optional node turned it into a lost day

- **Symptom.** The 14:40 UTC daily run failed 43 seconds in, at `research_followup`,
  with a 400: *"Function tools with reasoning_effort are not supported for
  gpt-5.6-luna in /v1/chat/completions ... or set reasoning_effort to 'none'."* No
  decision was recorded for 2026-08-10, 0 trades. Everything downstream of the failed
  node — decide, risk, rebalance, execute, journal, tweet — never ran.
- **Root cause.** Two, and the second is the interesting one.
  1. **The model quirk.** #112 moved both LLM tiers to the gpt-5.6 family on 08-08.
     That family applies a *server-side default* `reasoning_effort` which the
     `chat.completions` endpoint rejects when function tools are present. The code
     never sends `reasoning_effort` at all, so there was nothing in the diff to
     notice: the incompatibility is with a default we inherit. Verified against the
     API that both `gpt-5.6-luna` and `gpt-5.6-terra` 400 on tools, and both succeed
     with `reasoning_effort="none"` — the fix cannot be unconditional, because
     `gpt-4.1-mini` rejects that parameter as unrecognized.
  2. **The amplifier.** `research_followup` only *augments* the context — the fund can
     and does decide without it. But every node in the graph was fatal, so an optional
     enrichment ended the cycle. The cost of the model quirk should have been a
     slightly thinner run; instead it was the whole trading day.
- **Fix.** [#115](https://github.com/pradnyaw25/ai-portfolio-manager/pull/115) — the
  provider learns the quirk from the 400 and retries with `reasoning_effort="none"`,
  cached per model, folded into one `_adapt()` helper alongside the existing
  default-only-temperature workaround. [#116] — an `OPTIONAL_NODES` set in the daily
  graph: those nodes degrade to a warning plus a diagnostic and the cycle continues.
  Writing the test for that surfaced a third bug: `build_run_status_node` *overwrote*
  `run.warnings` with the freshly built status, so a degradation warning would never
  have reached `run_history` — the guard would have been silent. It merges now.
- **Detection gap.** CI was green on #112 and stayed green: no test exercises a live
  provider with tools, so the entire tool-calling path is only ever exercised in
  production. This is the repo's recurring shape: tests feed a shape production never
  produces (here, a mock client that accepts any kwargs), so a broken path survives
  with a passing suite. Nothing alerted, either — the failure was found only because
  someone asked about the day's run. `run_history.jsonl` *did* honestly record
  `status: failed` with the real error, which is an improvement on the 08-05 incident.
  Prediction scoring runs outside the cycle and still resolved the 08-03 batch, so the
  calibration dataset did not lose a day.
- **Article angle.** *A config change with no code in it.* The diff that broke this
  was three model strings; the failing parameter appears nowhere in the codebase. When
  behavior lives in a provider's defaults, "changing the model" is a code change with
  an invisible blast radius, and the only honest test is a live one. The second lesson
  is sharper and more portable: **an optional dependency wired as mandatory is a
  single point of failure you didn't know you had.** `retrieve_memory` degrades
  gracefully and has never cost a run; `research_followup` was one line of graph
  wiring away from the same treatment and cost a full day. Worth pairing with the
  08-05 entry — together they're a study in how an autonomous system's *error
  handling*, not its intelligence, decides what a bad day costs.

## 2026-08-06 · A late cron and a shared concurrency group cost the fund a whole trading day

- **Symptom.** No decisions, no journal entry, no site update, and no tweets for
  2026-08-06 — a normal Thursday. `data/portfolio_history.csv` jumps straight from
  08-05 to 08-07, and `run_history.jsonl` has no 08-06 rows at all. The fund simply
  wasn't there that day. Nothing reported an error, because from the pipeline's point
  of view nothing ever started.
- **Root cause.** Two causes compounding. GitHub's scheduler, which had been running
  59–101 minutes late on every observed run, fired the 14:40 UTC morning slot at 16:23
  (~103 min) and the 17:50 slot at **22:36 (~4h45m)** — far outside the delay the cron
  times were designed around. Meanwhile *both* daily slots sat in the same
  `concurrency: group: pages` as `deploy-pages.yml`. A concurrency group holds at most
  one in-progress plus one pending run, and a third arrival evicts the **pending** one.
  The badly delayed morning run was still queued when the afternoon run entered the
  group, so it was cancelled outright. The afternoon run then landed at 22:36, well
  after the close, and `market_hours_guard.py` correctly skipped it. Both slots gone.
- **Fix.** [#92](https://github.com/pradnyaw25/ai-portfolio-manager/pull/92) — key the
  group per cron slot (`daily-run-${{ github.event.schedule || github.run_id }}`) so
  each slot stays serialized against itself but the two can no longer evict each other;
  `workflow_dispatch` falls back to a per-run group. That permits the slots to overlap
  when the scheduler is >3h late, so the push step now rebases and retries up to 3
  times — the data files are append-mostly and each run's writes are idempotent.
  Tests pin the group and the rebase.
- **Detection gap.** Unusually, the platform *did* flag this one — the run shows
  `conclusion=failure` (job `cancelled`) and a red X in the Actions tab. Nobody was
  looking. There is no notification, no alert, and no check that the fund actually
  traded today; the Actions tab is only ever opened when something else prompts it. The
  application-side record is worse: `run_history.jsonl` only records runs that *start*,
  so a run cancelled before its first step leaves **no row at all** — the audit trail
  structurally cannot record its own absence. And every dashboard reads forward from
  whatever rows exist, so a missing day renders as a slightly shorter chart rather than
  a hole. Found 1 day later by scanning `portfolio_history.csv` for skipped weekdays
  during an unrelated review.
- **Article angle.** *The audit trail can't record the run that never happened.* Every
  observability surface here was built to explain what the fund **did**; none could
  represent a day it did nothing, so total absence was the one failure mode that looked
  like clean data. The deeper lesson is about inherited platform semantics: nobody
  chooses "evict the pending run" — it's a default buried in a concurrency group copied
  from the Pages deploy example, and it silently converts *lateness* into *loss*.
  Also a nice illustration of a fix that makes a failure non-fatal without fixing the
  underlying fragility: the scheduler is still 1–5h late, we just no longer die of it.

## 2026-08-05 · The fund timed out mid-decision and CI reported success

- **Symptom.** The 2026-08-05 morning run reached `decide_trades` and died with
  `Request timed out.` No trades were considered, no decision was journalled — and
  GitHub Actions marked the job **success**, committed, and deployed. The site published
  a normal-looking day on top of a run that never made a decision. The only evidence
  was a single `"status": "failed"` row in `data/run_history.jsonl` that no surface reads
  and no alert watches. It sat undiscovered for 2 days.
- **Root cause.** Two independent swallows in sequence. The LangGraph cycle catches a
  failed node, records it on the run, and returns normally so the run still journals and
  the site still publishes — deliberate, and correct. But `scripts/daily_run.py` then
  called `run_daily_cycle_graph(...)` and **discarded the returned run object**, falling
  off the end of `__main__` and exiting 0. The failure had been faithfully recorded and
  then thrown away one stack frame later.
- **Fix.** [#92](https://github.com/pradnyaw25/ai-portfolio-manager/pull/92) —
  `daily_run.py` returns 1 when the run records errors (logic moved into a `main()` so
  it's reachable from tests rather than stranded under `if __name__ == "__main__"`). The
  workflow runs it with `continue-on-error: true` so the journal and site still publish,
  then fails the job in a gate step placed *after* the deploy — failing immediately would
  have traded a silent failure for a lost audit trail, which is the same bug wearing a
  different hat.
- **Detection gap.** Nothing tested the script's exit code; all coverage stopped at the
  graph's return value, so the last four lines of the entry point — the part that decides
  whether the outside world hears about a failure — were untested. And `run_history.jsonl`
  had a `status` field that no dashboard, alert, or check ever read: recording a failure
  is not the same as reporting one. Notably the 60s `LLM_REQUEST_TIMEOUT` from the
  2026-07-08 incident *worked exactly as designed* here — it failed fast instead of
  hanging — and the fast failure was then rendered invisible by the exit code.
- **Article angle.** *Every layer handled the error correctly and the system still lied.*
  The graph caught it, the store recorded it, the log printed it — and the process exited
  0, so the only signal that crosses the boundary out of the process said "fine." Error
  handling is only as good as the narrowest channel it has to survive, and for a CI job
  that channel is one byte. Worth pairing with the observation that the previous
  incident's fix (fail fast on a stalled LLM call) is what *created* the failure this one
  hid — hardening one layer moves the failure to the next unguarded one.

## 2026-07-09 · The risk engine logged 22 "rejected trades" that were never trades

- **Symptom.** Today's decision journal showed **22 rejected trades** — every one a
  `HOLD` of 0 shares, "rejected" for `confidence 0.55 below minimum 0.60`. It read as if
  the risk engine had blocked 22 trade attempts; in reality the fund proposed **one**
  trade (BUY AAPL, approved) and held everything else. Across all history, **31 of 32**
  recorded "rejected trades" were these phantom HOLDs.
- **Root cause.** The portfolio manager emits a decision for *every* researched symbol,
  mostly `HOLD`. In `risk_manager.review()`, the minimum-**trade**-confidence gate ran
  inside `_base_rejection_reason` *before* the `if action == "HOLD": continue` skip — and
  unlike the sibling checks (`shares <= 0`, `symbol not in prices`), the confidence check
  had no `action != "HOLD"` guard. So every low-conviction HOLD was caught by the gate
  and appended to `rejected` before it could be skipped. A HOLD trades nothing, so it
  should be neither approved nor rejected.
- **Fix.** One guard — `if action != "HOLD" and confidence < MIN_TRADE_CONFIDENCE` — so a
  low-confidence HOLD passes through and is skipped as the no-op it is. Because the bad
  rows are already written into `decisions.jsonl` (history isn't rewritten), also filtered
  HOLDs out of every surface that renders rejected trades: the live journal
  (`decisions.html`), the prerendered decision pages (`decision_pages.py`), and the
  read-only MCP endpoint (`fund_data.py`). Regression test added.
- **Detection gap.** No test asserted what happens to a HOLD in review — tests covered
  low-confidence *BUYs* (correctly rejected) but never a HOLD, so the missing guard was
  invisible. And "rejected trades" was never sanity-checked against "trades actually
  proposed," so a list that was 96% phantom looked normal on the dashboard.
- **Article angle.** *A guardrail that's technically firing but semantically wrong.* The
  confidence gate worked; it just applied to the wrong set. The audit trail's credibility
  depends on it meaning what it says — "rejected trade" has to mean a trade that was
  actually going to happen, or the transparency is theater. Also: no-op actions leaking
  into an action log is a classic way audit trails quietly lie.

## 2026-07-08 · No LLM client timeout — one stalled call froze a whole batch for minutes

- **Symptom.** The new ablation harness "hung." The process was alive, CPU idle, and
  no new log lines for many minutes — indistinguishable from a deadlock. I killed and
  re-ran it twice, wrongly assuming my own code was stuck.
- **Root cause.** The OpenAI client was constructed as `OpenAI()` with **no `timeout`**.
  The SDK default is **600 seconds**, so a single stalled connection blocks the calling
  thread for up to ten minutes with no output. In a sequential batch (the harness, but
  equally the daily production run) one bad socket freezes everything behind it.
- **Fix.** Set `OpenAI(timeout=LLM_REQUEST_TIMEOUT)` with a 60s default
  (`src/config.py`); normal PM/debate calls finish in 10–15s, so 60s fails a genuine
  stall fast and lets the gateway's existing exponential-backoff retry recover. Also
  hardened the harness to skip a failed scenario rather than drop the whole variant.
- **Detection gap.** No test exercises a *stalled* (vs errored) connection — mocks
  return instantly, so the missing timeout was invisible. The liveness signal that
  finally diagnosed it was operational, not a test: `data/llm_calls.jsonl` is appended
  per completed call and unbuffered, so "process alive, zero new rows" = blocked on I/O.
- **Article angle.** Library defaults optimize for *don't give up*, not *don't hang my
  job* — every external client needs an explicit, aggressive timeout. And a per-call
  append-only log is the cheapest liveness probe you can have; buffered stdout hides
  exactly the failure you most need to see.

## 2026-07-06 · The grounding gate muzzled the fund over a rounding error

- **Symptom.** No daily tweet went out. The daily run had executed and Pages had
  deployed, so it looked like a deploy failure.
- **Root cause.** The tweet was generated fine, then the P2-3 **grounding gate
  blocked it**. The LLM judge flagged the *decision* because it said "AAPL increased
  **~5%**" when the context said **4.84%** — a rounding approximation treated as a
  fabrication. Any flagged decision hard-blocks publishing, so a ~0.16-point rounding
  difference killed the fund's main distribution channel. The judge was also
  *inconsistent*: in the same verdict it correctly declined to flag "26% vs 26.7%".
- **Fix.** [PR #40](https://github.com/pradnyaw25/ai-portfolio-manager/pull/40). Added
  an explicit `severity` (none/minor/material) to the grounding verdict; publication
  is now gated **only** on `material`. Minor imprecision (rounding, phrasing) is
  recorded on the decision for transparency but never blocks. Rewrote the judge prompt
  (v2) to define *material* narrowly and call out `4.84% → "about 5%"` as explicitly
  minor. Verified live against the real judge with a regression test.
- **Detection gap.** The grounding judge is `gpt-4o-mini` and unreliable at this
  precision call; the "don't flag rounding" instruction was in the prompt but ignored.
  256 tests, all against fakes — no test fed the *real* judge a rounding case. The tweet
  publish path returns a `blocked_grounding` status (not a job failure), so CI stayed
  green while the tweet silently died.
- **Article angle.** *The assurance feature built to protect the brand briefly muzzled
  it.* The correct move isn't to remove the gate (it's the differentiator) — it's to
  make it precise and gate on **materiality**, not any imperfection. Also: a "success"
  that silently drops the headline side effect is worse than a loud failure.

---

## 2026-07-06 · A "dry-run" that wasn't — a test tweet went live

- **Symptom.** While building the weekly "state of the fund" tweet, a run intended
  as a **dry-run** published a real tweet (with the chart image) to @GlassHouseFund.
- **Root cause.** `POST_TWEET=true` lives in `.env`. The dry-run was invoked with
  `env -u POST_TWEET` (unset in the shell), but `config.py` calls
  `load_dotenv()` — which only skips vars *already present* in the environment.
  Unsetting the shell var removed it, so dotenv happily loaded `POST_TWEET=true` from
  `.env` and the publish went out. The publish gate is a single boolean read from
  config at import; there was no dry-run switch independent of that config.
- **Fix / follow-up.** To truly suppress a post, set `POST_TWEET=false` *explicitly*
  (present in the environment → dotenv won't override it) rather than unsetting it.
  Follow-up: add an explicit `--dry-run` flag to `scripts/weekly_state_tweet.py` that
  forces `post_enabled=False` regardless of env. (The tweet itself was on-brand and
  was kept.)
- **Detection gap.** Disabling a real side effect relied on the *absence* of a flag,
  and a config layer (`.env` via dotenv) silently re-supplied it. There was no
  positive, explicit dry-run mode.
- **Article angle.** *The safest kill-switch is an explicit one.* "Unset the env var"
  is a trap when a `.env`/config layer can re-provide it — dangerous actions need a
  positive `--dry-run` flag, not the mere absence of `--live`. Precedent for a small
  section on operational footguns when building agents that touch the outside world.

---

## 2026-07-08 · The same judge, the same units — the weekly letter never published once

- **Symptom.** `data/investor_letters.jsonl` did not exist. The weekly investor letter
  had **never successfully published, not once**, and nobody noticed: the only workflow
  run (2026-07-05, run `28744889350`) "failed" quietly and the feature looked merely
  unstarted rather than broken.
- **Root cause.** `gather_letter_facts()` emits returns as **decimals** (`return_pct:
  0.0231`). The letter prompt said "Percentages are decimals (0.02 = 2%)", so the model
  correctly wrote **"2.31%"**. The grounding judge was then handed the *decimal* facts
  and the *percent* prose and concluded the letter had fabricated a number:
  > "The claim about a week-over-week return of 2.31% is incorrectly stated as '2.31%'
  > instead of the correct '0.0231' in decimal form."

  It graded that **material**, which hard-blocks publication. Reproduced live: with the
  raw facts, the judge read the position fact `0.5` as *"0.5%"* and called the letter's
  "50.00%" a material fabrication.
- **Fix.** Rather than argue with the judge, delete the disagreement. `format_facts_for_prompt()`
  renders every ratio-valued fact as a percent string once, and the **same** formatted
  view is handed to both the writer and the auditor — they can no longer disagree about
  units because they read identical numbers. Canonical decimals are still what gets
  *stored* in the journal, so the letters page stays machine-readable. Two live-judge
  regression tests: one that "2.31%" vs a `0.0231` fact publishes, one that an invented
  `$999` NVDA print still blocks `material`.
- **Detection gap.** This is **PR #40's incident, recurring.** That fix added the
  `severity` ladder *and* put "equivalent phrasing or units (0.12 vs \"12%\")" in the v2
  judge prompt as an explicit MINOR example — and the judge ignored its own prompt
  anyway. The lesson from #40 ("verify against the real judge") was learned for the
  *tweet* path only; the letter's grounding gate had **zero** tests, real or faked, and
  every letter test used a stub judge that returned `grounded=True`. Worse, the failure
  is silent by construction: `blocked_grounding` is a *status*, not an exception, so
  the script exits non-zero but the pipeline reads as "no letter this week."
- **Article angle.** *You cannot fix a prompt-following failure with more prompt.* #40
  told the judge, in writing, that `0.12` and `"12%"` are the same thing. It kept
  flagging them. The durable fix wasn't clearer instructions — it was removing the
  ambiguity from the input so there was nothing left to misjudge. Corollary for
  LLM-as-judge design: **give the judge and the generator the same view of the world.**
  A judge comparing prose against raw data is doing two jobs — unit conversion and
  fact-checking — and it will silently fail the one you didn't ask it to do. Also, twice
  now, an assurance feature has silently suppressed the artifact it was protecting; a
  gate that blocks should be at least as loud as a crash.

---

## Earlier incidents (from ROADMAP-V2 — expand with detail before writing)

> Stubs for the four incidents the audit already names. Fill in symptom/root-cause/
> fix/detection-gap from the relevant PRs and run logs before drafting Article 3.

### Qdrant payload-index 400 silently disabled memory
- **Symptom.** Memory retrieval returned nothing; decisions ran with no context.
- **Root cause.** A Qdrant payload-index 400 error was swallowed; memory degraded to
  empty without a loud signal. *(Expand: which call, which commit fixed it.)*
- **Article angle.** Graceful degradation that's *too* graceful hides real outages.

### After-hours stale-price trade (manual run)
- **Symptom.** A manual run traded at stale after-hours prices.
- **Root cause.** Manual `workflow_dispatch` bypasses the market-hours guard, which
  only gates *scheduled* runs. *(Expand with the specific run + fix.)*
- **Article angle.** Guards that protect the scheduled path but not the manual path.

### Repair-retries firing in production
- **Root cause / angle.** *(Expand: gateway repair-retry on invalid LLM output, seen
  live; what triggered it, cost/latency impact.)*

### Tweet double-post on crash-resume
- **Root cause / angle.** *(Expand: a non-idempotent side effect — tweet publish — ran
  twice when a run resumed after a crash; how it was guarded.)*
