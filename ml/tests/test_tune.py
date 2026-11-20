"""The random search: that it is reproducible, bounded, and starts from the defaults."""

import random

from drugwatch_ml.model import Settings
from drugwatch_ml.tune import SPACE, sample_settings, search, with_defaults_noted


def test_sampling_stays_inside_the_declared_space():
    generator = random.Random(0)
    for _ in range(200):
        settings = sample_settings(generator)
        for name, allowed in SPACE.items():
            assert getattr(settings, name) in allowed, name


def test_a_bagging_fraction_below_one_always_gets_a_frequency():
    """Otherwise LightGBM ignores it and those trials are duplicates of other trials."""
    generator = random.Random(1)
    for _ in range(200):
        settings = sample_settings(generator)
        if settings.bagging_fraction < 1.0:
            assert settings.bagging_freq == 1
        else:
            assert settings.bagging_freq == 0


def test_sampling_is_reproducible_from_the_seed():
    first = [sample_settings(random.Random(7)) for _ in range(3)]
    second = [sample_settings(random.Random(7)) for _ in range(3)]
    assert first == second


def test_the_first_trial_is_lightgbm_out_of_the_box():
    """So the result can be reported as "better than out of the box", not only "better than other
    random guesses"."""
    seen = []

    def fake_score(frame, folds, settings):
        seen.append(settings)
        return 0.1 * len(seen), [0.1]

    import drugwatch_ml.tune as tune_module

    original = tune_module.score_settings
    tune_module.score_settings = fake_score
    try:
        search(frame=None, folds=(), trials=4)
    finally:
        tune_module.score_settings = original
    assert seen[0] == Settings()
    assert len(seen) == 4


def test_the_search_returns_the_best_trial_not_the_last():
    def fake_score(frame, folds, settings):
        # best in the middle, so "returns the last" and "returns the best" differ
        score = {1: 0.1, 2: 0.9, 3: 0.2}[len(calls) + 1]
        calls.append(settings)
        return score, [score]

    calls = []
    import drugwatch_ml.tune as tune_module

    original = tune_module.score_settings
    tune_module.score_settings = fake_score
    try:
        best, best_score, results = search(frame=None, folds=(), trials=3)
    finally:
        tune_module.score_settings = original
    assert best_score == 0.9
    assert best is results[1][0]
    assert len(results) == 3


def test_the_log_names_only_what_changed():
    """A log line listing all nine parameters hides which one mattered."""
    assert with_defaults_noted(Settings()) == "all defaults"
    described = with_defaults_noted(Settings(num_leaves=127, learning_rate=0.01))
    assert "num_leaves=127" in described
    assert "learning_rate=0.01" in described
    assert "n_estimators" not in described
