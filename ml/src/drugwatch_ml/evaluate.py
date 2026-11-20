"""Score the test window once, against every baseline, and report what the number may be called.

Plan §9 step 6. This is the single-use evaluation: the test cutoffs 2025-04..2026-03 have not been
read by anything that chose a setting, and after this they are spent.

**The final model is the tuned one with `scale_pos_weight` returned to 1.0, and that was decided on
validation.** Step 4's search picked 3.0, which lifts PR-AUC from 0.379 to 0.383 - and inflates
every predicted probability: measured on the tuning folds, its mean prediction is 0.252 where the
outcome happens 12.6% of the time. Plan §4.3 publishes this number *as a probability*, so the
standing rule is: **if dropping the reweighting costs less than 0.01 PR-AUC, drop it**, because a
score that reads as "25% chance" when it means 12% is wrong in a way no caveat fixes. It cost
0.004 (ECE 0.126 -> 0.025, mean prediction 0.124 against a base rate of 0.126). The choice was made
on validation, before the test window was touched, which is what makes it a choice and not a
result.

Everything is reported three ways, because one headline number would average over groups that
differ: overall, for companies the model trained on, and for the 48% of test companies it has
never seen.

Run from ml/, with Postgres and MLflow up:
    caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.evaluate
"""

import mlflow
import pandas as pd

from drugwatch_ml import baselines, features, metrics, splits
from drugwatch_ml.model import RiskModel, Settings
from drugwatch_ml.tracking import start_run

# Step 4's search result, with the one deliberate change described above.
TUNED = Settings(
    n_estimators=100,
    learning_rate=0.1,
    num_leaves=7,
    min_child_samples=100,
    bagging_fraction=0.7,
    bagging_freq=1,
    lambda_l2=10.0,
    scale_pos_weight=3.0,
)
FINAL = Settings(**{**TUNED.__dict__, "scale_pos_weight": 1.0})
CALIBRATION_BUDGET = 0.01  # PR-AUC we are willing to give up for an honest probability


def metric_key(*parts: str) -> str:
    """An MLflow-safe metric name. It accepts letters, digits, `_-./ :` and nothing else, so a
    model called "LightGBM (tuned, calibrated)" is rejected mid-run - after the first metrics have
    already been written, which is the worst moment to find out.
    """
    safe = []
    for part in parts:
        cleaned = "".join(
            character if (character.isalnum() or character in "_-.") else "_"
            for character in part.strip()
        )
        safe.append("_".join(filter(None, cleaned.split("_"))))
    return "/".join(safe)


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    frame = features.load_features()
    features.check_columns(frame)
    folds, test = splits.protocol(str(frame["as_of_month"].max()))
    train, test_rows = splits.split(frame, test)
    labels = test_rows[features.LABEL_COLUMN].to_numpy()

    print(f"final fit on {len(train):,} rows (cutoffs <= {test.train_end})")
    print(
        f"test window {test.eval_start}..{test.eval_end}: {len(test_rows):,} rows, "
        f"{test_rows['manufacturer_id'].nunique():,} companies, {labels.mean():.1%} positive"
    )
    print("this window has not been read by anything that chose a setting. Scored once.")

    with start_run("test-evaluation", frame, step="5", purpose="single-use test"):
        mlflow.log_params({f"final/{k}": v for k, v in FINAL.as_tags().items()})
        mlflow.set_tag("test_window", f"{test.eval_start}..{test.eval_end}")

        # --- the model, and every baseline, on the same rows
        model = RiskModel(FINAL).fit(train)
        scored = {"LightGBM (tuned, calibrated)": model.score(test_rows)}
        scored.update(baselines.score_all(train, test_rows))

        section("TEST RESULTS")
        results = {}
        for name, scores in scored.items():
            result = metrics.evaluate(name, test_rows, labels, scores)
            results[name] = result
            print(result.line())
            for metric_name, value in result.as_metrics().items():
                mlflow.log_metric(metric_key("test", name, metric_name), value)

        # --- did it clear the bar, and is the margin real?
        section("DOES IT CLEAR THE BAR? (decision C: all three baselines, PR-AUC, CI excluding 0)")
        model_scores = scored["LightGBM (tuned, calibrated)"]
        cleared = True
        for name in [n for n in scored if n != "LightGBM (tuned, calibrated)"]:
            difference, lower, upper = metrics.bootstrap_difference(
                test_rows, labels, model_scores, scored[name]
            )
            beats = lower > 0
            cleared = cleared and beats
            print(
                f"  vs {name:32s} {difference:+.3f} PR-AUC"
                f"  95% CI {lower:+.3f}..{upper:+.3f}  {'CLEARS' if beats else 'DOES NOT CLEAR'}"
            )
            mlflow.log_metric(metric_key("test", "vs", name, "pr_auc_difference"), difference)
            mlflow.log_metric(metric_key("test", "vs", name, "ci_low"), lower)
            mlflow.log_metric(metric_key("test", "vs", name, "ci_high"), upper)
        mlflow.set_tag("test/clears_all_baselines", str(cleared).lower())
        print(
            f"\n  => {'PASS' if cleared else 'FAIL'}: "
            f"{'beats all three baselines' if cleared else 'does not beat all three'}"
        )

        # --- is the score a probability?
        section("IS IT A PROBABILITY? (plan §4.3 publishes it as one)")
        mean_prediction, base_rate = metrics.mean_prediction_vs_base_rate(labels, model_scores)
        ece = metrics.expected_calibration_error(labels, model_scores)
        brier = metrics.brier_score(labels, model_scores)
        print(f"  mean prediction {mean_prediction:.3f} against a base rate of {base_rate:.3f}")
        print(f"  expected calibration error {ece:.3f}   Brier score {brier:.3f}")
        print("\n  predicted vs observed, by equal-count decile:")
        table = metrics.reliability(labels, model_scores)
        for _, bin_row in table.iterrows():
            bar = "#" * max(1, round(bin_row["observed"] * 40))
            print(
                f"    {int(bin_row['rows']):>5} rows  predicted {bin_row['predicted']:.3f}"
                f"  observed {bin_row['observed']:.3f}  gap {bin_row['gap']:+.3f}  {bar}"
            )
        mlflow.log_metric("test/expected_calibration_error", ece)
        mlflow.log_metric("test/brier_score", brier)
        mlflow.log_metric("test/mean_prediction", mean_prediction)

        # --- who it works for
        section("WHO IT WORKS FOR (48% of test companies were never trained on)")
        known = set(train["manufacturer_id"])
        is_known = test_rows["manufacturer_id"].isin(known).to_numpy()
        for label, mask in (("seen during training", is_known), ("new since training", ~is_known)):
            subset = test_rows[mask]
            if not len(subset):
                continue
            result = metrics.evaluate(label, subset, labels[mask], model_scores[mask])
            print(result.line())
            for metric_name, value in result.as_metrics().items():
                mlflow.log_metric(metric_key("test", label, metric_name), value)

        # --- month by month, because a mean hides a bad month
        section("MONTH BY MONTH (a mean can hide a month where it failed)")
        monthly = []
        for month, group in test_rows.groupby("as_of_month", sort=True):
            mask = (test_rows["as_of_month"] == month).to_numpy()
            month_labels = labels[mask]
            if month_labels.min() == month_labels.max():
                continue
            monthly.append(
                {
                    "month": month,
                    "rows": len(group),
                    "positive": float(month_labels.mean()),
                    "roc_auc": metrics.roc_auc(month_labels, model_scores[mask]),
                    "pr_auc": metrics.pr_auc(month_labels, model_scores[mask]),
                    "p_at_20": metrics.precision_at_k(month_labels, model_scores[mask]),
                }
            )
        monthly_frame = pd.DataFrame(monthly)
        for _, month_row in monthly_frame.iterrows():
            print(
                f"  {month_row['month']}  {int(month_row['rows']):>5} rows"
                f"  {month_row['positive']:5.1%} positive"
                f"  ROC-AUC {month_row['roc_auc']:.3f}  PR-AUC {month_row['pr_auc']:.3f}"
                f"  P@20 {month_row['p_at_20']:.2f}"
            )
        worst = monthly_frame.loc[monthly_frame["pr_auc"].idxmin()]
        print(f"\n  worst month: {worst['month']} at PR-AUC {worst['pr_auc']:.3f}")
        mlflow.log_metric("test/worst_month_pr_auc", float(worst["pr_auc"]))

        section("SUMMARY")
        headline = results["LightGBM (tuned, calibrated)"]
        print(
            f"  ROC-AUC {headline.roc_auc:.3f} | PR-AUC {headline.pr_auc:.3f}"
            f" | P@20/month {headline.precision_at_k:.3f}"
        )
        print(f"  beats all three baselines: {'yes' if cleared else 'NO'}")
        print(
            f"  publishable as a probability: {'yes' if ece < 0.05 else 'no - present as a rank'}"
        )
        print("  reports history, not quality: always (plan §12, CLAUDE.md §6)")
    return 0 if cleared else 1


if __name__ == "__main__":
    raise SystemExit(main())
