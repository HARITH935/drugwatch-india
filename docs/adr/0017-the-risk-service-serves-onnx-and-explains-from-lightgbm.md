# ADR 0017 — The risk service predicts from ONNX, explains from LightGBM, and never reads the warehouse

- **Status:** Accepted
- **Date:** 2026-11-21
- **Decided by:** Harith (project owner), during Phase 8
- **Affects:** `ml-serving/`, `infra/ml-serving/`, `docker-compose.yml`, and Phase 9's Spring Boot API

---

## Context

Plan §9 Phase 8 asks for a FastAPI service with `/predict`, `/explain` and `/health`, running
ONNX Runtime, loading its model version from MLflow. Three things about that are under-specified,
and each has a wrong answer that works until it does not.

**1. `/explain` cannot be served from ONNX.** ONNX stores a tree ensemble as an inference graph:
thresholds, child pointers and leaf values, which is all a prediction needs. SHAP needs to walk
every path and know the training-set coverage of each node, and that information is not in the
graph. So an ONNX-only service can return a score and cannot explain it — and §4.3 requires an
explanation beside every score.

**2. A service that reads the warehouse couples two uptimes.** `mart_ml_features` holds the 28
features, so the obvious design is `/predict?manufacturer_id=X` with the service fetching the row.
That means database credentials in the serving container, a connection pool, and a prediction API
that is down whenever Postgres is busy — for a model whose answer depends only on 28 numbers.

**3. The conversion is not bit-exact.** ONNX runs tree ensembles in float32 while LightGBM
accumulates in float64, so the two disagree at around 1e-7. Measured on the real test window: max
difference 1.37 × 10⁻⁷.

## Options considered

| Option | Trade-off |
|---|---|
| **A. ONNX only** | One model in memory, smallest image. But `/explain` becomes impossible, so §4.3's explanations would have to move into the Spring Boot API or disappear. |
| **B. LightGBM only** | SHAP works; `/predict` and `/explain` trivially agree. But ONNX and ONNX Runtime are mandated (plan §6) and the portability they buy — a served model with no Python training stack — is a real property for Phase 12. |
| **C. Both: ONNX for `/predict`, LightGBM for `/explain`** | Two representations of one model in memory (~47 KiB of ONNX beside the booster, so the cost is nil) and the obligation to prove they agree. |
| **D. Service fetches features from `gold` itself** | One call from the caller's point of view. Credentials in the serving container, a second consumer of the warehouse, and a prediction API that shares the database's failure modes. |

## Decision

**Option C, with the service stateless (so, not D).**

- **`/predict` answers from ONNX.** The portable path, as mandated.
- **`/explain` computes SHAP over the original LightGBM model**, and returns **the ONNX score**, so
  the number in an explanation is always the number `/predict` gives for the same row.
- **Startup refuses to serve if the two paths disagree** by more than half the smallest unit a
  reader will ever see (5 × 10⁻⁴, i.e. 0.05 of a percentage point). A score shown as "14.2%" cannot
  be moved by a smaller difference, so that is the threshold rather than an arbitrary epsilon.
- **The service takes features in the request body and never touches Postgres.** Phase 9's Spring
  Boot API already reads `gold` (plan §5) and posts what it read.
- **A missing feature is a 422 naming it; an unexpected feature is also a 422.** Several features
  are legitimately null — a share is null when the window held no findings to divide — so null is a
  *value* the model was trained to read. Filling an absent field with 0 would answer a different
  question and say nothing about having done so.

**The approved explanation wording is imported from `drugwatch_ml.explain`, not copied.** The
28-phrase vocabulary, the 17 forbidden words and the reporting-history clause are public text about
named Indian companies (CLAUDE.md §6). A second copy is a second thing to keep correct, and the
copy is the one that drifts. That makes `drugwatch-ml` a runtime dependency of `ml-serving`, which
is a deliberate coupling: the alternative is two sets of words that can disagree about what may be
said about a company.

**Verification of the conversion is a build step with a veto.** `build_onnx` converts, compares
against the original on the **real test window** — not on random numbers, which exercise leaves no
manufacturer ever reaches — and **deletes the artifact and exits non-zero** if it disagrees. The
checks are: max absolute difference, Spearman correlation, whether any row moved below something
the original ranked strictly beneath it, and whether the top-20 set is unchanged.

That last pair replaced the obvious check, which was wrong. Comparing `argsort` outputs reported a
changed ranking at **zero** real inversions and Spearman 1.000000: when the original gives two rows
exactly equal scores a stable sort keeps input order, while a 1e-8 difference in the converted model
orders them. The fix was to count only pairs the original ranked *strictly*.

## Consequences

- **Measured agreement:** 22,070 test rows, max difference 1.37 × 10⁻⁷, mean 3.07 × 10⁻⁸, Spearman
  1.000000, 0 inverted rows, identical top-20. Nothing a reader could see changes.
- Phase 9 must fetch the 28 features from `gold` and post them. That is more work for the caller
  than passing an id, and it keeps the model's availability independent of the warehouse's.
- The container needs `libgomp1`. Without it `import lightgbm` fails at start with
  `libgomp.so.1: cannot open shared object file`, which reads like a Python packaging problem and
  is not one — it is the same OpenMP runtime `brew install libomp` provides on the Mac.
- **One uvicorn worker**, because each worker loads its own model and its own SHAP explainer. Phase
  12 may raise it, with measurements behind the change rather than a default.
- The ONNX artifact is **not committed**: it is rebuilt from the registry, and a binary derived from
  a tracked model version is not a source file. `ml-serving/artifacts/` is git-ignored.
- MLflow has no authentication (ADR 0016), and this service has none either. Both are bound to
  `127.0.0.1`. Phase 12 must put the service behind the API rather than exposing it.
