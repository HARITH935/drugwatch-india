# ADR 0015 — scikit-learn is a direct dependency of `ml/`

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decided by:** Harith (project owner)
- **Affects:** `ml/` (Phase 7), and Phase 8's check that the ONNX model matches the original

---

## Context

Plan §12 requires a **logistic regression baseline** and the metrics **ROC-AUC, PR-AUC and
precision@top-K**. The mandatory stack (§6) names LightGBM, SHAP, RapidFuzz and MLflow for data
science. It does not name scikit-learn, which is where both the baseline and those metrics live.

Three things were checked before asking:

- **It is already installed.** Resolving `lightgbm shap mlflow` against Python 3.13 pulls in
  `scikit-learn==1.9.1` regardless: `shap` needs it, `mlflow` needs it, and `skops` (an mlflow
  dependency) needs it. So this adds **nothing** to the environment and nothing to the lockfile's
  download size - it only makes an existing transitive dependency a declared one.
- **Writing the metrics by hand is worse, not purer.** ROC-AUC is the one metric already computed
  by hand in this project, in SQL, to measure the baselines during planning (the Mann-Whitney rank
  sum with ties averaged). That was 10 lines for one number with no confidence interval. PR-AUC has
  a genuine subtlety - whether to interpolate between points - that a hand-rolled version would get
  wrong silently, and the result would be unanswerable in an interview.
- **Relying on a transitive dependency is the actual risk.** `ml/` will `import sklearn` either
  way. Not declaring it means the day `shap` drops the dependency, the training pipeline breaks
  with an ImportError and the lockfile gives no clue why it was ever there.

## Options considered

| Option | Trade-off |
|---|---|
| **A. Hand-write the baseline and the metrics** | No new declared dependency. But a hand-rolled logistic regression needs its own optimiser, and hand-rolled PR-AUC is a correctness risk on the one number the phase is judged by. The code would be mine to defend rather than the standard implementation everyone reviews against. |
| **B. Use it transitively, without declaring it** | Nothing to approve. Worst of both: the import exists, the guarantee does not, and `uv.lock` records it as something else's dependency. |
| **C. Declare it in `ml/pyproject.toml`** | Needs this ADR. Honest about what the code imports, and costs nothing because it is already resolved. |

## Decision

**Option C.** `scikit-learn>=1.9,<2` is a direct dependency of `ml/`, used for exactly three
things:

1. `LogisticRegression` - plan §12's second baseline.
2. `roc_auc_score`, `average_precision_score` - plan §12's metrics. `average_precision_score` is
   the non-interpolated PR-AUC, which is the one to use for a rare-positive problem.
3. `StandardScaler`, inside the logistic-regression baseline only. Logistic regression needs scaled
   inputs to converge; LightGBM does not and will not get it.

**What it is not used for:** the train/test split (the protocol is time-based and hand-built, so
`train_test_split` must never appear - it shuffles), cross-validation helpers (same reason), and
the model itself. LightGBM remains the model, as §6 mandates.

## Consequences

- One more declared dependency in `ml/`, zero more installed packages.
- Phase 8 gets the same metric functions to prove the ONNX export matches the original model, so
  "matches" is measured the same way in both phases.
- The rule stays: any *other* use of scikit-learn - a different model, a resampler, an imputer -
  needs its own decision. This ADR approves a baseline and three metrics, not a second modelling
  library.
