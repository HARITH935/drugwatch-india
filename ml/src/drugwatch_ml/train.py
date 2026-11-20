"""Tune LightGBM on the tuning folds and report whether it clears the baselines' bar.

Plan §9 step 5. Every number here comes from the three tuning folds; the test window is scored
once, in step 5. So this answers "did tuning find something better than the baselines on data the
model has not trained on", not "is the model good" - that is a different question with a
different, single-use answer.

Each trial is logged to MLflow as a nested run, so the search is inspectable rather than a single
number with a shrug behind it.

Run from ml/, with Postgres and MLflow up:
    uv run --env-file ../.env python -m drugwatch_ml.train --trials 40
"""

import argparse

import mlflow

from drugwatch_ml import baselines, features, metrics, splits, tune
from drugwatch_ml.model import RiskModel
from drugwatch_ml.tracking import start_run


def baseline_bar(frame, folds) -> tuple[str, float]:
    """The best baseline's mean PR-AUC across the same folds - recomputed rather than copied from
    step 3's output, so the comparison cannot drift from the thing it compares against."""
    totals: dict[str, float] = {}
    for fold in folds:
        train, evaluate_on = splits.split(frame, fold)
        labels = evaluate_on[features.LABEL_COLUMN].to_numpy()
        for name, scores in baselines.score_all(train, evaluate_on).items():
            totals[name] = totals.get(name, 0.0) + metrics.pr_auc(labels, scores)
    means = {name: total / len(folds) for name, total in totals.items()}
    best = max(means, key=lambda key: means[key])
    for name, value in sorted(means.items(), key=lambda item: -item[1]):
        print(f"  {name:34s} PR-AUC {value:.3f}")
    return best, means[best]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=40, help="random search trials")
    parser.add_argument("--seed", type=int, default=0)
    arguments = parser.parse_args()

    frame = features.load_features()
    features.check_columns(frame)
    folds, test = splits.protocol(str(frame["as_of_month"].max()))
    print(f"{len(frame):,} labelled rows; tuning on {len(folds)} folds.")
    print(f"the test window {test.eval_start}..{test.eval_end} is NOT touched here.\n")

    print("the bar, recomputed on these folds:")
    bar_name, bar = baseline_bar(frame, folds)
    print(f"  -> must beat PR-AUC {bar:.3f} ('{bar_name}')\n")

    with start_run("lightgbm-tuning", frame, step="4", purpose="random search"):
        mlflow.log_metric("bar/best_baseline_pr_auc", bar)
        mlflow.set_tag("bar/best_baseline", bar_name)
        mlflow.log_param("trials", arguments.trials)

        def log_trial(index, total, settings, mean_score, per_fold, best_so_far):
            marker = " <- best" if mean_score >= best_so_far else ""
            print(
                f"  [{index:>3}/{total}] PR-AUC {mean_score:.3f}"
                f"  {tune.with_defaults_noted(settings)[:72]}{marker}"
            )
            with mlflow.start_run(nested=True, run_name=f"trial-{index}"):
                mlflow.log_params({k: v for k, v in settings.as_tags().items()})
                mlflow.log_metric("mean_pr_auc", mean_score)
                for fold, score in zip(folds, per_fold, strict=True):
                    mlflow.log_metric(f"{fold.name}/pr_auc", score)

        print(f"random search, {arguments.trials} trials (trial 1 is LightGBM's defaults):")
        best, best_score, results = tune.search(
            frame, folds, trials=arguments.trials, seed=arguments.seed, on_trial=log_trial
        )

        defaults_score = results[0][1]
        print(f"\nLightGBM out of the box:  PR-AUC {defaults_score:.3f}")
        print(f"LightGBM tuned:           PR-AUC {best_score:.3f}")
        print(f"best baseline:            PR-AUC {bar:.3f}  ('{bar_name}')")
        print(f"\nchosen settings: {tune.with_defaults_noted(best)}")

        mlflow.log_metric("lightgbm/defaults_pr_auc", defaults_score)
        mlflow.log_metric("lightgbm/tuned_pr_auc", best_score)
        mlflow.log_params({f"best/{k}": v for k, v in best.as_tags().items()})

        # Is the tuned model ahead of the bar by more than noise? Decision C's rule, applied on
        # the last tuning fold - the test window's own version of this is step 5's, computed once.
        train, evaluate_on = splits.split(frame, folds[-1])
        labels = evaluate_on[features.LABEL_COLUMN].to_numpy()
        model_scores = RiskModel(best).fit(train).score(evaluate_on)
        baseline_scores = baselines.score_all(train, evaluate_on)[bar_name]
        difference, lower, upper = metrics.bootstrap_difference(
            evaluate_on, labels, model_scores, baseline_scores
        )
        clears = lower > 0
        print(
            f"\non {folds[-1].name}, tuned LightGBM minus '{bar_name}':"
            f" {difference:+.3f} PR-AUC (95% CI {lower:+.3f}..{upper:+.3f})"
        )
        print(f"  -> {'clears the bar' if clears else 'DOES NOT clear the bar'} on this fold")
        mlflow.log_metric("lightgbm/minus_baseline_pr_auc", difference)
        mlflow.log_metric("lightgbm/minus_baseline_ci_low", lower)
        mlflow.log_metric("lightgbm/minus_baseline_ci_high", upper)
        mlflow.set_tag("lightgbm/clears_bar_on_validation", str(clears).lower())

        importances = RiskModel(best).fit(train).importances()
        used = int((importances > 0).sum())
        print(f"\nfeatures the model actually split on: {used} of {len(importances)}")
        for name, gain in importances.head(5).items():
            print(f"  {gain:12,.0f}  {name}")

    print("\nstep 5 refits these settings on everything up to", test.train_end, "and scores the")
    print("test window once. Nothing above is a claim about held-out performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
