"""Register the model, its explanations, and the test results it must be judged by.

Plan §9 step 8: *"Track all runs and register the best model in MLflow."* What gets registered is
the model from step 5 - tuned on validation, reweighting dropped for calibration, fitted on every
cutoff up to the test embargo - together with the artifacts that make it usable and the numbers
that say what it is worth.

**The test results are attached to the registered version, not only to a run.** A model in a
registry outlives the conversation that produced it: whoever loads it in Phase 8 must be able to
read "statistically tied with logistic regression" off the thing itself rather than find it in a
commit message.

**The plain LightGBM model is what is registered**, not an ONNX export. Phase 8 converts it for
serving predictions, but `/explain` needs SHAP, and SHAP needs the tree structure that ONNX
discards. Both come from this one artifact.

Run from ml/, with Postgres and MLflow up:
    caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.publish
"""

import json
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in a terminal; must precede pyplot
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from mlflow.models import infer_signature  # noqa: E402

from drugwatch_ml import features, metrics, splits  # noqa: E402
from drugwatch_ml.evaluate import FINAL  # noqa: E402
from drugwatch_ml.explain import Explainer, explanation_sentences  # noqa: E402
from drugwatch_ml.model import RiskModel  # noqa: E402
from drugwatch_ml.tracking import start_run  # noqa: E402

MODEL_NAME = "manufacturer-risk"
EXPLAIN_SAMPLE = 3000  # enough for a stable global importance; SHAP over 22,070 rows is wasteful


def importance_plot(importance: pd.Series, path: Path) -> None:
    """Horizontal bar chart of mean |SHAP|, largest at the top."""
    top = importance.head(15).iloc[::-1]
    figure, axes = plt.subplots(figsize=(9, 6))
    axes.barh(range(len(top)), top.to_numpy(), color="#4C72B0")
    axes.set_yticks(range(len(top)), [name.replace("_", " ") for name in top.index], fontsize=9)
    axes.set_xlabel("mean |SHAP| contribution (log-odds)")
    axes.set_title("What the risk score relies on\n(reporting history, not medicine quality)")
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def main() -> int:
    frame = features.load_features()
    features.check_columns(frame)
    _, test = splits.protocol(str(frame["as_of_month"].max()))
    train, test_rows = splits.split(frame, test)
    labels = test_rows[features.LABEL_COLUMN].to_numpy()

    model = RiskModel(FINAL).fit(train)
    scores = model.score(test_rows)
    print(f"fitted on {len(train):,} rows; scoring {len(test_rows):,} test rows")

    explainer = Explainer(model)
    sample = test_rows.sample(min(EXPLAIN_SAMPLE, len(test_rows)), random_state=0)
    importance = explainer.global_importance(sample)
    error = explainer.additivity_error(sample)
    print(
        f"SHAP additivity error: {error:.2e} (must be ~0 for the sentences to be about the score)"
    )
    if error > 1e-6:
        print("REFUSING to register: the explanations do not add up to the predictions")
        return 1

    with start_run("publish", frame, step="7", purpose="register the model") as run:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)

            plot_path = folder / "shap_global_importance.png"
            importance_plot(importance, plot_path)
            mlflow.log_artifact(str(plot_path))

            importance.rename("mean_abs_shap").to_csv(folder / "shap_global_importance.csv")
            mlflow.log_artifact(str(folder / "shap_global_importance.csv"))

            # Worked examples across the score range, so a reader can see what an explanation
            # looks like for a high, middling and low score rather than only the extreme.
            examples = []
            order = np.argsort(model.score(sample))
            for label, position in (
                ("highest score", int(order[-1])),
                ("median score", int(order[len(order) // 2])),
                ("lowest score", int(order[0])),
            ):
                row = sample.iloc[position]
                examples.append(
                    {
                        "which": label,
                        "as_of_month": str(row["as_of_month"]),
                        "score": round(float(model.score(sample.iloc[[position]])[0]), 4),
                        "explanation": explanation_sentences(
                            explainer.contributions(sample, position)
                        ),
                    }
                )
            # Manufacturer ids are deliberately absent: these are illustrations of the wording,
            # and a worked example naming a real company is a published allegation (ADR 0003).
            (folder / "example_explanations.json").write_text(json.dumps(examples, indent=2))
            mlflow.log_artifact(str(folder / "example_explanations.json"))
            print("\nworked examples (no company named - ADR 0003):")
            for example in examples:
                print(f"  {example['which']} ({example['score']:.3f}):")
                for line in example["explanation"]:
                    print(f"    {line}")

            # The model itself, with a signature so Phase 8 cannot feed it the wrong columns.
            matrix = train[list(features.FEATURE_COLUMNS)]
            signature = infer_signature(matrix, model.score(train))
            info = mlflow.lightgbm.log_model(
                model.model,
                name="model",
                signature=signature,
                input_example=matrix.head(3),
                registered_model_name=MODEL_NAME,
            )
            print(f"\nregistered {MODEL_NAME} from {info.model_uri}")

            # What it is worth, attached to the registered version itself.
            test_metrics = {
                "test_roc_auc": metrics.roc_auc(labels, scores),
                "test_pr_auc": metrics.pr_auc(labels, scores),
                "test_precision_at_20_per_month": metrics.precision_at_k_by_month(
                    test_rows, labels, scores
                ),
                "test_expected_calibration_error": metrics.expected_calibration_error(
                    labels, scores
                ),
                "test_brier_score": metrics.brier_score(labels, scores),
                "shap_additivity_error": error,
            }
            for name, value in test_metrics.items():
                mlflow.log_metric(name, value)

            client = mlflow.MlflowClient()
            # `get_latest_versions` is deprecated along with registry stages; searching by name
            # and taking the highest version number is the supported replacement.
            versions = client.search_model_versions(f"name='{MODEL_NAME}'")
            version = max(versions, key=lambda candidate: int(candidate.version)).version
            client.set_registered_model_alias(MODEL_NAME, "production", version)
            for name, value in test_metrics.items():
                client.set_model_version_tag(MODEL_NAME, version, name, f"{value:.4f}")
            # The honest summary, on the artifact rather than in a commit message.
            client.set_model_version_tag(
                MODEL_NAME,
                version,
                "limitations",
                "Reporting history, not quality. Statistically tied with logistic regression on"
                " the 2025-04..2026-03 test window (+0.011 PR-AUC, 95% CI -0.004..+0.026)."
                " Much weaker on companies absent from training (PR-AUC 0.269 vs 0.438)."
                " Under-predicts: trained at a 12.8% base rate, tested at 16.0%.",
            )
            client.set_model_version_tag(
                MODEL_NAME, version, "test_window", f"{test.eval_start}..{test.eval_end}"
            )
            print(f"version {version} tagged, alias 'production' set")
            print(f"run {run.info.run_id[:8]}")

    print("\ntop of the global importance:")
    for name, value in importance.head(6).items():
        print(f"  {value:.4f}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
