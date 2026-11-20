"""Evaluate the three baselines on the tuning folds, and log them to MLflow.

Step 3's output. These numbers are the bar LightGBM has to clear, so they are produced on the
**tuning folds only** - the test window is scored once, at step 5, and tuning against it would
make it a validation set with a flattering name.

Run from ml/, with Postgres and MLflow up:
    uv run --env-file ../.env python -m drugwatch_ml.run_baselines
"""

import mlflow

from drugwatch_ml import baselines, features, metrics, splits
from drugwatch_ml.tracking import start_run


def main() -> int:
    frame = features.load_features()
    features.check_columns(frame)
    tuning, test = splits.protocol(str(frame["as_of_month"].max()))

    print(f"{len(frame):,} labelled rows. Baselines on the {len(tuning)} tuning folds.")
    print(f"(the test window {test.eval_start}..{test.eval_end} is untouched)\n")

    per_fold: dict[str, list[metrics.Result]] = {}
    opened = start_run("baselines", frame, step="3", purpose="the bar LightGBM must clear")
    with opened as run:
        for fold in tuning:
            train, evaluate_on = splits.split(frame, fold)
            labels = evaluate_on[features.LABEL_COLUMN].to_numpy()
            print(f"{fold.describe()}  ->  {len(evaluate_on):,} rows to score")

            scores = baselines.score_all(train, evaluate_on)
            for name, values in scores.items():
                result = metrics.evaluate(name, evaluate_on, labels, values)
                per_fold.setdefault(name, []).append(result)
                print(result.line())
                for metric_name, value in result.as_metrics().items():
                    mlflow.log_metric(f"{fold.name}/{name}/{metric_name}", value)
            print()

        print("mean across the tuning folds:")
        summary = {}
        for name, results in per_fold.items():
            mean_roc = sum(r.roc_auc for r in results) / len(results)
            mean_pr = sum(r.pr_auc for r in results) / len(results)
            mean_at_k = sum(r.precision_at_k for r in results) / len(results)
            summary[name] = (mean_roc, mean_pr, mean_at_k)
            print(
                f"  {name:34s} ROC-AUC {mean_roc:.3f}  PR-AUC {mean_pr:.3f}"
                f"  P@{metrics.DEFAULT_K}/month {mean_at_k:.3f}"
            )
            mlflow.log_metric(f"mean/{name}/roc_auc", mean_roc)
            mlflow.log_metric(f"mean/{name}/pr_auc", mean_pr)
            mlflow.log_metric(f"mean/{name}/precision_at_k_per_month", mean_at_k)

        # The bar LightGBM has to clear, recorded as one number so step 4 cannot drift from it.
        best_pr = max(value[1] for value in summary.values())
        best_name = max(summary, key=lambda key: summary[key][1])
        mlflow.log_metric("bar/best_baseline_pr_auc", best_pr)
        mlflow.set_tag("bar/best_baseline", best_name)
        print(f"\nthe bar: PR-AUC {best_pr:.3f}, set by '{best_name}'")

        # Is the bar really the logistic model's, or is it tied with a one-column ranking?
        # Decision C requires an interval excluding 0 before claiming one model beats another, and
        # that applies to the baselines too - otherwise the bar itself is a coin flip.
        train, evaluate_on = splits.split(frame, tuning[-1])
        labels = evaluate_on[features.LABEL_COLUMN].to_numpy()
        scores = baselines.score_all(train, evaluate_on)
        difference, lower, upper = metrics.bootstrap_difference(
            evaluate_on,
            labels,
            scores["logistic regression"],
            scores["ranking: reports in last 24m"],
        )
        verdict = "clearly ahead" if lower > 0 else "NOT distinguishable"
        print(
            f"\non {tuning[-1].name}, logistic minus count-ranking PR-AUC:"
            f" {difference:+.3f} (95% CI {lower:+.3f}..{upper:+.3f}) - {verdict}"
        )
        print("  (companies resampled, not rows: one company's 6 monthly rows are not 6 cases)")
        mlflow.log_metric("bar/logistic_minus_ranking_pr_auc", difference)
        mlflow.log_metric("bar/logistic_minus_ranking_ci_low", lower)
        mlflow.log_metric("bar/logistic_minus_ranking_ci_high", upper)

        # What the linear baseline leaned on - useful later as a sanity check against SHAP.
        weights = baselines.LogisticBaseline().fit(train).coefficients()
        print("\nlogistic regression's five largest weights (scaled, so comparable):")
        for name, weight in weights.head(5).items():
            print(f"  {weight:+.3f}  {name}")
        print(f"\nlogged to MLflow run {run.info.run_id[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
