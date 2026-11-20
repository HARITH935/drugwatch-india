"""Random search over LightGBM settings, scored on the tuning folds only.

Plan §9 step 5. Random search rather than a grid: with 9 parameters a grid of even three values
each is 19,683 combinations, while random search over the same ranges finds a comparable optimum
in a few dozen trials - and it needs no new library, which a Bayesian optimiser would.

**The test window is not touched here.** Every number this produces comes from the three tuning
folds. The chosen settings are then refit once, in step 5, against the test window.

Each trial's score is the **mean PR-AUC across the folds**, because that is the metric decision C
set the bar on, and the mean rather than the best fold so a setting that only works in one period
cannot win.
"""

import random
from dataclasses import replace

import pandas as pd

from drugwatch_ml import features, metrics, splits
from drugwatch_ml.model import RiskModel, Settings

# The ranges searched. Wide enough to include both a small cautious model and a large flexible one,
# because which of those suits 40,000 rows and 28 features is exactly what is being asked.
SPACE = {
    "n_estimators": [100, 200, 300, 500, 800],
    "learning_rate": [0.01, 0.02, 0.05, 0.1],
    "num_leaves": [7, 15, 31, 63, 127],
    # Larger than LightGBM's default of 20 is usually right here: a leaf built from 5 rows of one
    # manufacturer's history is noise that looks like a rule.
    "min_child_samples": [20, 50, 100, 200],
    "feature_fraction": [0.6, 0.8, 1.0],
    "bagging_fraction": [0.7, 0.85, 1.0],
    "lambda_l2": [0.0, 1.0, 10.0],
    # 1.0 = untouched probabilities; ~6.8 = balanced at a 12.8% positive rate. Searched because it
    # trades ranking against calibration (see model.py note 3).
    "scale_pos_weight": [1.0, 3.0, 6.8],
}


def sample_settings(generator: random.Random) -> Settings:
    """One random point. `bagging_freq` follows from `bagging_fraction`: LightGBM silently ignores
    a bagging fraction below 1 unless the frequency is set, which would make a third of the search
    space secretly identical."""
    chosen = {name: generator.choice(values) for name, values in SPACE.items()}
    bagging_freq = 0 if chosen["bagging_fraction"] >= 1.0 else 1
    return Settings(bagging_freq=bagging_freq, **chosen)


def score_settings(
    frame: pd.DataFrame, folds: tuple[splits.Fold, ...], settings: Settings
) -> tuple[float, list[float]]:
    """Mean PR-AUC across the folds, and each fold's own score."""
    per_fold = []
    for fold in folds:
        train, evaluate_on = splits.split(frame, fold)
        scores = RiskModel(settings).fit(train).score(evaluate_on)
        labels = evaluate_on[features.LABEL_COLUMN].to_numpy()
        per_fold.append(metrics.pr_auc(labels, scores))
    return sum(per_fold) / len(per_fold), per_fold


def search(
    frame: pd.DataFrame,
    folds: tuple[splits.Fold, ...],
    trials: int = 40,
    seed: int = 0,
    on_trial=None,
) -> tuple[Settings, float, list[tuple[Settings, float, list[float]]]]:
    """Random search. Returns the best settings, its mean PR-AUC, and every trial tried.

    LightGBM's defaults are trial 1 rather than a random point, so the search can be reported as
    "better than out of the box" and not only "better than other random guesses".
    """
    # S311: a seeded, reproducible generator is exactly what is wanted here - these are
    # hyperparameter draws, not secrets, and the seed is what makes a search repeatable.
    generator = random.Random(seed)  # noqa: S311
    candidates = [Settings()] + [sample_settings(generator) for _ in range(trials - 1)]

    results = []
    best_settings, best_score = candidates[0], float("-inf")
    for index, settings in enumerate(candidates, start=1):
        mean_score, per_fold = score_settings(frame, folds, settings)
        results.append((settings, mean_score, per_fold))
        if mean_score > best_score:
            best_settings, best_score = settings, mean_score
        if on_trial:
            on_trial(index, len(candidates), settings, mean_score, per_fold, best_score)
    return best_settings, best_score, results


def with_defaults_noted(settings: Settings) -> str:
    """Only the settings that differ from LightGBM's defaults, so a log says what was changed."""
    default = Settings()
    changed = {
        name: value
        for name, value in settings.as_tags().items()
        if value != default.as_tags()[name]
    }
    return ", ".join(f"{name}={value}" for name, value in changed.items()) or "all defaults"


def tightened(settings: Settings, **overrides) -> Settings:
    """A copy with some settings replaced - used by the final refit, which keeps everything the
    search chose."""
    return replace(settings, **overrides)
