# Glasshouse Fund — Automated Content Strategy

Glasshouse Fund should publish evidence from a running experiment, not manufacture a
daily market opinion. Content is a downstream product of structured fund events:
decisions, risk interventions, disagreements, resolved predictions, memory use,
experiments, and incidents.

The desired voice is specific, falsifiable, technically curious, concise, and candid
about uncertainty. Avoid generic finance-bot language, promotional certainty, and
repetition.

## Objectives

1. Make the technical system understandable without manual daily writing.
2. Give people recurring reasons to follow the experiment beyond portfolio returns.
3. Turn wins, mistakes, rejected trades, incidents, and null results into useful
   evidence.
4. Drive readers to durable artifacts: decision pages, experiments, scorecards,
   investor letters, and the repository.
5. Keep publishing safe, grounded, idempotent, and able to choose silence.

## Editorial principles

- **Facts before prose:** generation receives a bounded structured fact packet.
- **Receipts over claims:** link to the relevant decision, prediction, or experiment.
- **Explain mechanisms:** show what memory, debate, risk code, or replay changed.
- **Report mistakes plainly:** a wrong or miscalibrated prediction is content.
- **Novelty is required:** skip candidates that repeat a recent symbol and thesis.
- **No forced cadence:** publish nothing when no candidate clears the quality bar.
- **Paper trading is explicit:** never imply real capital, customers, or advice.
- **Public claims fail closed:** quarantine content when validation is unavailable.

## Content streams

| Stream | Trigger | Target cadence | Core artifact |
|---|---|---:|---|
| Decision receipt | An executed trade with a material thesis | Event-driven | Trade, evidence, bear case, risk result |
| Prediction card | A distinctive new prediction | 2–3/week maximum | Direction, confidence, horizon, falsifier |
| Resolution card | A prediction reaches its horizon | Event-driven | Outcome vs SPY, confidence, calibration |
| Risk intervention | A trade is rejected, capped, or resized | Event-driven | Proposed vs approved trade and rule |
| Debate split | Analyst conviction spread clears a threshold | 1/week | Bull, bear, risk, and PM synthesis |
| Memory resurfaced | Prior evidence materially affects a decision | 1/week | Source, age, retrieval reason, effect |
| Experiment result | Replay, eval, or ablation completes | 1/week maximum | Variant comparison and limitations |
| Engineering incident | A production failure is understood | Event-driven | Symptom, containment, root cause, fix |
| Weekly letter | Weekly workflow succeeds and is grounded | 1/week | Performance, changes, lessons, outlook |
| Monthly scorecard | Month closes | 1/month | Return, drawdown, calibration, cost, mistakes |

Automated daily updates are supporting content, not the product. One strong weekly
experiment result is more valuable than five variations of “AAPL has momentum.”

## Suggested weekly rhythm

- **Monday:** distinctive prediction or watch item
- **Tuesday:** retrieval, replay, cost, or engineering observation
- **Wednesday:** analyst disagreement or risk intervention
- **Thursday:** resolved prediction, calibration update, or mistake
- **Friday:** compact weekly scorecard
- **Sunday:** investor-letter summary or thread
- **Any day:** material trade, incident, or newly resolved experiment

This is a set of eligible slots, not a requirement to fill every slot.

## Content event contract

Producers should emit a typed event rather than prose. A minimal shape is:

```json
{
  "event_id": "content_...",
  "type": "prediction_resolved",
  "occurred_at": "2026-07-17T20:00:00Z",
  "run_id": "run_...",
  "symbol": "AAPL",
  "importance": 0.87,
  "novelty": 0.76,
  "facts": {},
  "evidence_ids": ["prediction_...", "decision_..."],
  "canonical_url": "https://glasshousefund.com/...",
  "expires_at": "2026-07-20T20:00:00Z"
}
```

Recommended event types:

- `trade_executed`
- `trade_rejected`
- `trade_resized`
- `prediction_created`
- `prediction_resolved`
- `debate_diverged`
- `memory_influenced_decision`
- `experiment_completed`
- `run_failed`
- `incident_resolved`
- `weekly_letter_published`
- `monthly_scorecard_ready`

Facts must include their units and source identities. Render percentages, currency,
and dates deterministically rather than asking the model to calculate them.

## Selection pipeline

```text
Fund and engineering events
        ↓
Eligible content candidates
        ↓
Deduplication and cooldowns
        ↓
Novelty × importance × educational value × recency
        ↓
Structured template or grounded generation
        ↓
Numeric, citation, compliance, and length validation
        ↓
Branded card/chart rendering
        ↓
Scheduled publication with idempotency key
        ↓
Outcome and engagement record
```

### Ranking

Start with deterministic scoring:

```text
score = 0.30 × importance
      + 0.25 × novelty
      + 0.20 × educational_value
      + 0.15 × evidence_quality
      + 0.10 × recency
```

Apply hard exclusions before ranking:

- expired event
- missing public evidence
- same event already published
- symbol/thesis inside cooldown
- grounding unavailable or failed
- private or licensed source text that cannot be republished
- routine no-trade update with no new lesson

### Cooldowns and diversity

- Maximum one routine post per day.
- No repeated symbol/thesis inside three days unless a material event changed it.
- No more than two consecutive posts of the same content type.
- Reserve at least two weekly slots for non-performance content.
- A weekly letter supersedes a generic weekly performance update.
- Prefer a resolved prediction over a new prediction when both are eligible.

Use normalized thesis tags and embedding similarity for semantic deduplication only
after deterministic symbol/type rules. Log the reason every candidate was selected or
rejected.

## Generation and validation

Use deterministic templates for scorecards, resolved predictions, and risk receipts.
Use an LLM only when synthesis adds value, such as explaining a debate or incident.

Every generated post must pass:

1. **Fact validation:** all numbers and named events match the supplied packet.
2. **Citation validation:** referenced evidence exists and is public.
3. **Grounding validation:** prose claims are entailed by the packet.
4. **Compliance validation:** paper-trading disclosure is present where needed and
   the text does not present personalized advice.
5. **Length validation:** the rendered post, URLs, and tags fit before publishing.
6. **Novelty validation:** the final text does not substantially repeat recent posts.

Do not truncate a completed post. Calculate the platform budget first and regenerate
or use a shorter template. Hashtags are optional; prefer zero or one useful project
tag over generic finance hashtags.

Publication states:

- `candidate`
- `selected`
- `generated`
- `validated`
- `scheduled`
- `posted`
- `quarantined`
- `failed_retryable`
- `failed_terminal`
- `skipped_duplicate`
- `skipped_low_value`

An unavailable grounding or fact validator results in `quarantined`, never `posted`.

## Format patterns

### Risk intervention

> The model proposed **{proposal}**. The deterministic risk engine approved
> **{approved}** because **{rule}**. Agents propose; code disposes. {link}

### Resolved prediction

> We gave **{symbol}** a **{confidence}%** chance to {direction} SPY over {horizon}.
> Result: {symbol_return} vs {spy_return}. **{outcome}**. The {confidence_bucket}
> confidence bucket is now {bucket_record}. {link}

### Debate split

> The analysts disagreed most on **{symbol}**: bull {bull_confidence}, bear
> {bear_confidence}, risk {risk_confidence}. The PM chose **{action}** because
> {deciding_constraint}. Full receipt: {link}

### Engineering incident

> Today the fund {symptom}. Execution was {containment}. Root cause: {cause}. We added
> {fix} and {regression_test}. Incident note: {link}

These are factual frames, not mandatory wording.

## Visual system

Generate a small set of reusable branded cards:

- Decision receipt
- Prediction resolved: correct / incorrect / calibration warning
- Proposed versus risk-approved trade
- Bull/bear/risk conviction spread
- Weekly performance and drawdown
- Experiment comparison: quality, cost, and latency
- Incident timeline

Each card should include the date, run or experiment identity, Glasshouse mark, and a
short URL. Charts must begin from canonical structured data, not values copied from
generated prose. Include accessible alt text assembled from the same facts.

## Measurement

Record publication outcome alongside its source event:

- impressions and engagement when available
- link clicks
- profile and repository visits when measurable
- content type, symbol, visual type, and posting time
- generation model, cost, and validation result
- manual intervention count

Optimize for qualified interest rather than raw impressions. Useful north-star
signals are decision-page visits, GitHub visits, demo runs, MCP usage, subscribers,
and substantive replies.

Review monthly:

- Which streams earn clicks or meaningful discussion?
- Which symbols or formats are overrepresented?
- How often did the system correctly choose silence?
- How many posts were quarantined, duplicated, or manually corrected?
- Did published predictions and claims remain calibrated and grounded?

Do not let engagement metrics influence portfolio decisions or prediction scoring.

## Implementation backlog

1. Introduce the typed `ContentEvent` schema and durable content-event store.
2. Emit events from trades, risk review, predictions, debate, memory, evals, and run
   status without changing those components' decisions.
3. Build deterministic eligibility, cooldown, ranking, and deduplication.
4. Add templates and bounded generation from structured fact packets.
5. Make grounding unavailable fail closed for public content.
6. Add branded image rendering and accessible descriptions.
7. Add scheduling, retry, idempotency, and the existing kill switch.
8. Export a public content archive and internal selection diagnostics.
9. Add monthly format-performance reporting without feeding it into trading logic.

The executable first increment is W02 in
[`PRODUCT-ROADMAP.md`](PRODUCT-ROADMAP.md).
