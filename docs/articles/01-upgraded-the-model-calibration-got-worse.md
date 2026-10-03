# I upgraded the model and the calibration got worse

*Scoring 483 LLM stock predictions, with dated receipts.*

> **Draft, 2026-10-02.** Piece 1 of the series in `ARTICLE-SERIES.md`. Every number
> below comes from `data/predictions.jsonl` as of this date, bucketed after the
> boundary fix in #125. Re-pull the tables before publishing if the store has moved.

---

Every LLM application ships a confidence number. The model says "0.7" and the UI shows
a bar. Almost nobody checks whether 0.7 means anything.

I run a paper-trading fund where a language model makes the calls. Twice a day it
looks at 34 names, and for each one it says whether the stock will beat or lag the S&P
500 over the next five days, and over the next thirty, with a confidence. Every call
is written down with the date, the price at the time, and the model that made it. When
the window closes, a script grades the call against what actually happened. Nothing
gets edited. The whole thing publishes itself, right or wrong.

By October it had 483 graded calls. In August, with 177, I had a story I liked. Then I
upgraded the model, and the extra 300 calls took the story apart.

## The headline

| | |
|---|---|
| Graded calls | 483 |
| Hit rate | 51.1% |
| Mean stated confidence | 62% |
| Brier score | 0.2686 |

The Brier score is the mean squared error between stated confidence and outcome. A
model that said "50%" to every question and was right half the time would score
exactly 0.25. This model scored 0.2686. **Its stated confidence made it worse than
admitting it didn't know.**

The calibration table says where the error lives:

| stated confidence | n | actual hit rate | gap |
|---|---|---|---|
| 50–60% | 177 | 54.2% | −1.4 |
| 60–70% | 205 | 47.3% | **−15.7** |
| 70–80% | 93 | 54.8% | **−17.4** |
| 80–90% | 8 | 37.5% | −43.2 (n=8, don't lean on it) |

Below 60% the model is roughly honest. Above 60% the number is decoration. The calls it
was most sure about were no better than the ones it shrugged at.

## The upgrade

On 2026-08-08 I moved the fund from `gpt-4.1-mini` to `gpt-5.6-terra` for the
decision-making tier. I had a reason. I ran both through an eight-scenario eval with a
fixed LLM judge, and terra scored 4.08 and 4.21 out of 5 across two runs against
mini's 3.79 and 3.71, at about eight times the price per scenario. Better reasoning,
on paper, for money I could afford. It was the responsible-looking choice.

Every prediction carries a tag for the model that made it, so the swap is a clean
seam in the data.

| model | window | graded | hit rate | Brier | mean confidence |
|---|---|---|---|---|---|
| gpt-4.1-mini | Jul 8 → Aug 7 | 237 | 55.7% | 0.2550 | 64% |
| gpt-5.6-terra | Aug 10 → Sep 21 | 239 | 46.4% | 0.2815 | 61% |

The newer, pricier, better-reasoning model was wrong more often and more confidently.
Its 60–70% bucket is the single worst row in the whole dataset:

| gpt-5.6-terra, stated | n | actual |
|---|---|---|
| 50–60% | 122 | 54.9% |
| 60–70% | 91 | **37.4%** |
| 70–80% | 24 | 37.5% |

Ninety-one times terra said "about 64%". It was right 34 of those times. If it had
said "50%" instead, its Brier score would have been 0.25. The confidence cost it
0.03, which in this metric is the difference between "slightly informative" and
"worse than a shrug".

Mini, by contrast, barely lost anything to its confidence: 0.2550 against the same
0.25 floor. It was overconfident too, but mildly, and its most confident bucket
(70–80%, n=66) actually hit 61%.

One receipt, because the aggregate hides what this looks like on a given day. On
2026-08-10, terra's first day, it called **SNDK to lag the S&P over five days at 81%
confidence**, its most confident call of the whole run. SNDK beat the index by 44
points that week. That is one call out of 239 and it proves nothing on its own. It is
just what an 81% looks like from the inside.

## The part I had to retract

The August draft of this piece had a flattering finding. With 177 calls, the model's
"lag the index" calls hit 67% and its "beat the index" calls hit 44%. I had a tidy
paragraph: the model is good at spotting laggards and bad at picking winners, the
opposite of how a stock-picker markets itself.

Here is what I had not checked. In July, **59% of the names in the universe lagged the
S&P**. The model mostly said "lag". A model that said "lag" every single time, without
reading a headline, would have hit 59.1% on mini's window. Mini hit 55.7%.

Then the regime flipped. On terra's window 52% of names beat the index, the constant
answer became "beat", and the laggard edge evaporated: terra's "lag" calls hit 44.5%.

| model | best constant call on its window | model's hit rate | gap |
|---|---|---|---|
| gpt-4.1-mini | always "lag": 59.1% | 55.7% | −3.4 |
| gpt-5.6-terra | always "beat": 52.3% | 46.4% | −5.9 |

**Neither model ever beat the dumbest possible strategy on its own window.** The
laggard story was the July base rate wearing a trench coat. It is gone from the
predictions page, and the page now prints the constant-call baseline next to the hit
rate so I can't make that mistake again in public.

## What I think is going on

I don't know, and the data can't fully separate the candidates. But three things are
worth saying.

**The eval graded reasoning; the market graded calls.** The judge that preferred terra
read a rationale and scored it on structure, grounding and risk awareness. Terra writes
a better rationale. The scoreboard doesn't read the rationale. A more fluent argument
for the wrong direction scores identically to a clumsy one, and a more fluent model
may simply be more persuasive to itself, which is what the 64%-stated / 37%-actual
row looks like.

**Confidence granularity is not calibration.** Mini's favourite confidence values were
0.6, 0.55 and 0.7. Terra's were 0.56, 0.57, 0.55, 0.58 and 0.59. Two extra decimal
places of apparent precision, and the second decimal carried no information at all.

**The windows don't overlap, so regime is a confound.** Mini worked a month where most
names lagged; terra worked a month where most names beat. Terra's graded calls are
also almost entirely five-day windows (238 of 239), while mini's were a 170/67 mix of
five- and thirty-day, because the thirty-day calls terra opened were still open when
I pulled this. That is why the right next experiment is both models on the same prompt
on the same day, which is what the fund is doing next. Until then, "terra is worse" is
a sequential comparison with a known confound, not a verdict.

## What's worth stealing

**Publish the constant-call baseline next to the hit rate.** A directional hit rate
means nothing against 50%. It has to beat "always say the majority outcome" for its
own window, and that number changes month to month. If I had printed it from day one,
the laggard paragraph would never have been written.

**Tag every prediction with the model that made it.** This was a one-line change
(`model` on the prediction record) and it is the only reason the swap is a finding
rather than an unexplained kink in one aggregate curve.

**Audit the sampler before the metric.** The first version of this system only
recorded a prediction when the fund actually bought something: about seven calls a
month, every one a name that had already cleared every risk gate. The sampler was
conditioned on the exact thing I was trying to measure. Now every researched name
gets a call every run, whether or not anything trades. That is the difference between
7 and 483.

**Non-overlapping windows, short horizons.** One open call per (symbol, horizon); a
new one opens only when the old one resolves. Naive daily 30-day windows overlap
29/30 and inflate N by an order of magnitude. Five-day windows are why a curve existed
three weeks in rather than six months.

**Check your buckets.** While pulling these numbers I found that `int(0.7 / 0.1)` is
6, not 7, in floating point. Every call at exactly 0.6 or 0.7 confidence, the model's
two favourite values, had been sitting in the row below the one it belonged in on the
public table: 78 of 483. The hit rate and Brier score were unaffected. The curve was
mislabelled for three months.

## What I'm not claiming

This is paper trading with simulated capital. The calls are directional, relative to
SPY, not return forecasts. Two models in sequence over two different months is not an
A/B test. Thirty-four names is a small universe. The 80–90% bucket has eight calls in
it and should be ignored. The total LLM spend for four months of this was $5.44, which
tells you the models are cheap, not that the experiment is.

What I am claiming is narrower and, I think, holds: on 483 dated, graded calls, stated
confidence above 60% carried no information, a model that scored better on a
reasoning eval calibrated worse live, and at no point did either model beat a constant
answer on its own window. All of it is on the predictions page, with the per-model
curves and the baseline, updated every trading day, and the raw JSONL is in the repo.

*Live scoreboard: glasshousefund.com/predictions.html · Code and data:
github.com/pradnyaw25/ai-portfolio-manager*

---

## Launch notes (not part of the piece)

- **HN title:** *I made an LLM make 483 stock predictions, scored them, then upgraded the model and it got worse*
- **First comment, paraphrased:** paper trading; the interesting artifact is the
  per-model calibration curve and the constant-call baseline, not the returns; the
  honest confound is that the two models ran in sequence, and the same-day
  multi-model comparison is the next thing the fund publishes.
- **X thread opener:** the SNDK receipt (81% confident, wrong by 44 points) and the
  terra 60–70% row, then the link.
- **Do not** quote the 80–90% bucket alone, the 7,300-char decision page as typical,
  or the hit rate without the baseline.
- Re-pull every table on publish day. Terra's 30-day calls resolve through October
  and will change its row.
