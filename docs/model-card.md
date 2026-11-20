# Model card — DrugWatch India manufacturer risk score

- **Model:** `manufacturer-risk`, version 1 (MLflow alias `production`)
- **Built:** 2026-11-20, Phase 7
- **Type:** LightGBM binary classifier, 100 trees, 7 leaves
- **Code:** `ml/src/drugwatch_ml/`, reproducible from the git commit tagged on the MLflow run

---

## What it predicts

**For a manufacturer already present in the CDSCO archive, the probability that at least one of
its batches is named in a CDSCO alert during the next 6 months.**

Every word of that matters:

- **"already present in the archive"** — a company gets no input rows before its first reported
  finding, so the model cannot score a company that has never been reported. See *Who it does not
  work for*.
- **"named in an alert"** — the outcome is a *publication event*, not a quality event.
- **"next 6 months"** — counted from a monthly cutoff, from the month after it to the sixth.

## What it does NOT predict

**It does not predict whether a company's medicines are safe, or whether it will do anything
wrong.** The archive records batches that were *sampled and tested*. Sampling is not random: a
company tested often has more chances to appear, and a company never sampled cannot appear at all.

The score therefore reflects **reporting history**, not quality (plan §12, CLAUDE.md §6). This
sentence travels with every explanation the model produces and must appear wherever a score is
shown.

## How well it works

Measured once, on cutoffs **2025-04 to 2026-03** — 22,070 manufacturer-months, 2,242 companies,
16.0% positive. The window was never used to choose a feature, a hyperparameter or a threshold.

| model | ROC-AUC | PR-AUC | precision@20/month |
|---|---|---|---|
| **this model** | **0.706** | **0.385** | 0.738 |
| logistic regression over the same features | 0.693 | 0.373 | **0.754** |
| ranking by batches reported in 24 months | 0.687 | 0.324 | 0.638 |
| rule: "reported in the last 6 months" | 0.623 | 0.214 | 0.337 |

PR-AUC is the headline rather than ROC-AUC because positives are rare (16%): ROC-AUC is dominated
by how well the many easy negatives are ordered, while PR-AUC only reflects the top of the list,
which is the part anyone acts on. A random ranking scores PR-AUC ≈ 0.16 here, not 0.5.

### ⚠️ It is not better than a linear model

Against logistic regression the difference is **+0.011 PR-AUC with a 95% confidence interval of
−0.004 to +0.026** — the interval includes zero. On this test window, **this model and a plain
logistic regression are statistically indistinguishable**, and on precision@20 per month the
logistic model is slightly ahead (0.754 against 0.738).

It does beat the other two baselines decisively (+0.171 and +0.061, both with intervals well clear
of zero), so the features carry real signal beyond "was it reported recently". The gradient-boosted
model is simply not adding anything on top of a linear combination of them.

The confidence intervals resample **companies**, not rows: one manufacturer contributes up to 12
monthly rows, which are one company's history seen twelve times rather than twelve independent
observations.

**Why this model was shipped anyway:** the plan's stack mandates LightGBM, the point estimates are
ahead on two of three metrics, and SHAP attributions come free from a tree model. The honest
summary is that the choice of algorithm is not what makes this score work.

### Who it does not work for

**1,071 of the 2,242 companies in the test window (48%) had no rows in training at all**, because
a company's history begins at its first reported finding. Performance splits sharply:

| | rows | companies | PR-AUC | precision@20/month |
|---|---|---|---|---|
| seen during training | 14,052 | 1,171 | **0.438** | 0.725 |
| new since training | 8,018 | 1,071 | **0.269** | 0.408 |

A score for a company the model has not seen before is considerably weaker and should be presented
with less weight, or not at all.

### Is the number a probability?

Yes, within about 2.4 percentage points. Expected calibration error **0.024**, Brier score 0.119,
mean prediction 0.136 against an observed rate of 0.160, and the reliability curve is monotonic
across all ten deciles (top decile: predicted 0.458, observed 0.486).

**It under-predicts slightly and systematically.** All ten deciles sit below the observed rate,
because the model trained on cutoffs averaging 12.8% positive and was tested on a period averaging
16.0% — CDSCO's publication volume grew. **Phase 9 should recalibrate monthly rather than refit**,
and a shown score should never be presented as more precise than its nearest percent.

This required a deliberate choice. The hyperparameter search preferred `scale_pos_weight` 3.0,
which scored PR-AUC 0.383 on validation but predicted **0.252 on average where the outcome happens
12.6% of the time** — it doubled every probability. Since the score is published as a probability,
the reweighting was dropped for a cost of 0.004 PR-AUC, taking calibration error from 0.126 to
0.025. That decision was made on the validation folds, before the test window was touched.

### Month by month

PR-AUC ranges from **0.302** (2025-06) to **0.448** (2026-03), rising steadily as each company
accumulates history. No month collapses; a single average would have hidden both ends.

## What it uses

28 features from `gold.mart_ml_features`, all computed from months **at or before** the cutoff.
Verified in Phase 4 against an independent recomputation of every row: 0 wrong features, 0 wrong
labels, 0 leaked labels.

By mean absolute SHAP contribution:

| feature | mean \|SHAP\| |
|---|---|
| batches reported in the last 24 months | 0.397 |
| months since the most recent reported batch | 0.272 |
| different kinds of medicine reported in 12 months | 0.093 |
| share of all archive reports over 12 months | 0.084 |
| share of test failures that were dissolution tests | 0.054 |
| states whose laboratories reported a batch | 0.048 |

Two features are never used at all: `state_lab_reports_12m` and `central_lab_share_12m`.

**No feature is allowed to act as a calendar.** The archive's raw 12-month testing volume
correlates 0.855 with calendar time, so it was never given to the model; only the company's
*share* of it (correlation −0.180) is a feature. A test rejects any feature correlating above 0.7
with the cutoff, because the test period is strictly later than training and "recent means
positive" would score well for entirely the wrong reason.

### Features the plan asked for that do not exist

- **"Any spurious-drug association" (§12)** — impossible by design, not by omission. A spurious
  finding means the *pack* was judged counterfeit, so the company named on it is the brand somebody
  copied, i.e. the victim. `fact_nsq_sample` carries no `manufacturer_id` for spurious rows at all
  (CLAUDE.md §6), so nothing can attach them to a company even by a careless join.

## How the explanations work

Each score comes with up to three SHAP contributions rendered in fixed, neutral wording. SHAP is
exact for tree models, and additivity is checked before anything is registered: measured error
**2.9 × 10⁻¹⁵**, so the sentences describe the prediction actually shown.

Example, for a real test row with no company named:

> Mainly batches reported in the last 24 months (19) raises it.
> Also states whose laboratories reported a batch in 12 months (5) raises the score.
> Also months since the most recent reported batch (0) raises the score.
> This reflects how often batches have been reported, not the quality of the company's medicines.

The wording is a fixed vocabulary of 28 phrases, one per feature, reviewable in one screen. A
feature with no approved phrase **raises an error instead of falling back to its column name**, so
a new feature cannot reach a public sentence before someone has written neutral words for it. Tests
reject a list of forbidden words (fraud, fake, counterfeit, unsafe, substandard, offender,
blacklist, avoid…) and require the reporting-history clause on every explanation.

## Known limitations, in one list

1. **Reporting history, not quality.** Non-random sampling; a company never tested cannot appear.
2. **Statistically tied with logistic regression** on the test window.
3. **Much weaker on the 48% of companies absent from training** (PR-AUC 0.269 vs 0.438).
4. **Under-predicts** because the base rate drifted up between training and test.
5. **Cannot score a company with no reported findings**, which is most manufacturers in India.
6. **A 6-month horizon only**; it says nothing about longer-term behaviour.
7. **Trained on 2,609 companies** that appear in CDSCO alerts, not on the Indian industry.
8. **No spurious-finding feature**, by design (see above).

## Ethical and legal constraints

- Published scores must show the reporting-history caveat, the batch number, the alert month and a
  link to the original CDSCO document (CLAUDE.md §6).
- A score is never presented as a verdict, a grade or a recommendation to avoid a company.
- "Not found" never means "guaranteed safe".
- CDSCO data is not published on a live site until permission is recorded in
  `docs/permissions.md` (ADR 0003). **Neither permission email has been sent.**

## Reproducing it

```bash
cd ml
caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.train --trials 40  # tuning
caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.evaluate          # the test, once
caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.publish            # register
```

Every MLflow run records its git commit, whether the working tree was dirty, and a fingerprint of
the feature table (rows, columns, newest cutoff). `evaluate` exits non-zero when the model fails
the bar, so a failure is a status rather than a paragraph somebody has to read.
