# Methodology — the moat is the *history*, not the agent

> In one line: turn "said it and moved on" into an **auditable performance record** — written down
> daily, scored objectively the next day, bucketed by horizon, with confidence intervals, and
> robust to exogenous shocks.
>
> The code can be copied. **The compounding, tamper-evident track record cannot.**

Implementation: [`ledger.py`](ledger.py), [`integrity.py`](integrity.py), [`selfreview.py`](selfreview.py).

---

## 1. Why this is the most valuable thing

In an AI market-review system, the **agents, prompts, data sources and email rendering are all
commodities** — a fork gets you all of it. The only thing that is neither copyable nor renewable is:

> **The predict → verify → attribute → calibrate loop, and the compounding history it produces.**

- **Un-copyable** — others can take the code, not "what I said yesterday and whether it was right".
- **Compounding** — it is the only asset that gets *more* valuable with time.
- **A qualitative jump** — most "AI stock agents" are just confident paragraphs. Only when every
  output is scored against tomorrow's real prices does it become a **falsifiable forecaster**.

---

## 2. The iron rule: scoring must be deterministic

Models rationalize (they write "partial hit" for a miss). So: **hit/miss is computed from price
data; the model only writes attribution.**

| | Old way | This project |
|---|---|---|
| Who scores | the model writes ✅/❌ | `ledger.py` computes from real daily K |
| Rule | changes every time | fixed, reproducible, auditable |
| Model's job | score + attribute | **attribute only** |

> Observed: same predictions — "model self-scored" hit rate 100%, "deterministic verification" 14.3%.
> The self-assessment bias shows up immediately.

---

## 3. Scoring rules

**Level predictions** (number + keyword)
- resistance / target → did the period **high** touch it
- support → did the period **low** touch it
- breakout / reclaim → did a **close** exceed it
- breakdown / loss → did a **close** fall below it
- key level → did the period range cross it

**Direction** → see §4 (volatility-normalized).
**Window**: estimated from wording (next day = 1 / next 1-2 weeks = 10 / default 5 sessions);
the return is measured **from the prediction day's close** (so a 1-day call is measured correctly).
**Aggregate**: hits/rules → ✅ Hit / ⚠️ Partial / ❌ Miss / Unverifiable.

---

## 4. Short-term noise: normalize, bucket, label — don't pretend

"Predicting tomorrow" is close to a coin flip. Handle noise explicitly:

1. **Volatility-normalized direction.** Noise band = `PRED_VOL_MULT × daily vol × √N`. A move only
   counts as a directional hit if it **exceeds the band**; inside the band is recorded as
   **undecided (not scored)**; beyond it in the *opposite* direction is a miss.
2. **Bucket by horizon.** Next-day / ~1 week / 1-2 weeks — never one number hiding the short term.
3. **Wilson 95% CI.** Always attach an interval; if it crosses 50%, don't conclude.
4. **Brier score for probabilistic calls.** Score "optimistic 30% / base 50% / pessimistic 20%";
   confident-and-wrong is penalized more. Compare to the uniform baseline (0.667).
5. **Shock days, transparently.** Sessions with `|move| > 2.5× daily vol` are tagged "exogenous
   shock"; report **both** raw and ex-shock hit rates — never silently exclude.
6. **Beat a naive baseline.** If the market rose 60% of days and you're bullish 60% of the time,
   45% is *worse than always-long*.

---

## 5. When the hit rate is low

**Diagnose before touching rules.** The fatal move is tuning thresholds until it "looks good".

1. **Real or noise?** Wilson interval crossing 50% → not conclusive.
2. **Break it down:** by horizon, by capability (levels accurate but direction wrong?), by regime,
   by confidence (is a 80%-confidence call actually more accurate?).
3. **Compare to a naive baseline.**
4. **Change the *prediction form*, not the *scoring rule*:** switch to scenario+probability+trigger,
   use range/conditional calls, require explicit invalidation, stop short-term directional calls.
5. **Red line: freeze & version the scoring spec.** Only forward-looking; **never re-score history.**

### Anti-patterns that destroy the moat
1. Tune thresholds to look good, then recompute history.
2. Write "partial hit" for a miss (= back to model self-scoring).
3. Hide everything behind one overall number.
4. Delete samples / switch tickers when the rate is low.

---

## 6. The loop: the report must write *machine-readable* predictions

Verification requires parseable forecasts. So the generator is forced to write
`resistance 7850`, `support 7700`, `break below 27000 → trim`, `reclaim 7800`, plus explicit
scenario probabilities. → **write it cleanly today, judge it objectively tomorrow, feed the
calibration into tomorrow's analysis.**

---

## 7. Long-run form: from verification to an AI Research Track Record

A single ✅/❌ is raw material. The asset is aggregating them **by dimension and regime**:

- **Capability**: Direction / Sector / Event / Risk. Falsifiability varies — direction, sector
  (relative ETF return) and risk (drawdown threshold) are computable; **event/catalyst often is
  not cleanly falsifiable**, so record it conditionally or mark it "unverifiable" and **keep it out
  of the hit rate**.
- **Regime**: trend/chop × low/mid/high volatility — "40% directional in chop, 70% in trends" is
  actionable; "63%" is not.
- **Confidence calibration**: isolate ≥80%-confidence calls; if they aren't more accurate, that's
  **overconfidence**.

`get_research_track_record` produces this dashboard; the analyst then **lowers stated conviction on
its weak dimensions**. That is the concrete meaning of "learning" here — *calibration, not retraining*.

---

## 8. Tamper-evidence & self-review

- **Tamper-evident ledger** (`integrity.py`): each day's predictions are appended to a
  **hash-chained, append-only** file (`prev` + `hash`, never overwritten). `verify_chain()` detects
  any edit; `reconcile()` detects a report changed after commit.
- **Self-review** (`selfreview.py`): `python main.py --self-review` feeds the **computed error
  structure** (weak buckets / typical misses / overconfidence / shock sensitivity / baseline) into an
  LLM that writes *"why have I been wrong?"* — **attribution, never scoring**; if the sample is small
  it must say "not enough data to conclude".

---

## 9. Operating rhythm

- **Run every day after the US close** — samples are the compounding asset.
- While n < 30-50, **watch trends, don't conclude**; review the dashboard regularly.
- **Change the scoring spec prospectively and rarely**, and record the date.

---

## 10. Red lines (pin these up)

1. **Score only from price data**; the model only attributes.
2. **Freeze & version the spec; never re-score history.**
3. **Don't conclude on small samples** (Wilson CI).
4. **Slice by horizon and regime** — reject the average illusion.
5. **Shock days are shown side-by-side**, not silently excused.
6. **Beat a naive baseline**, or the number is meaningless.

> Keep these six and the record stays valuable; break one and all the work is worthless.
