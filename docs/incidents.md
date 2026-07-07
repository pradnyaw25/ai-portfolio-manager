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
