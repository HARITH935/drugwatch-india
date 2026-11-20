"""The three baselines. The tests that matter are the leak checks on the fitted one."""

import numpy as np
import pandas as pd
import pytest

from drugwatch_ml.baselines import (
    LogisticBaseline,
    reported_recently,
    reports_24m_ranking,
    score_all,
)
from drugwatch_ml.features import FEATURE_COLUMNS, LABEL_COLUMN


def fake(rows: int = 400, seed: int = 0) -> pd.DataFrame:
    """A frame with the real column set, enough signal to fit, and nulls where the real mart has
    them (a share is null when the window held no findings to divide)."""
    generator = np.random.default_rng(seed)
    data = {column: generator.random(rows) for column in FEATURE_COLUMNS}
    data["reports_6m"] = generator.integers(0, 4, rows).astype("float64")
    data["reports_24m"] = generator.integers(0, 30, rows).astype("float64")
    frame = pd.DataFrame(data)
    frame.loc[frame["reports_6m"] == 0, "assay_share_12m"] = np.nan
    frame["manufacturer_id"] = [f"m{i % 50}" for i in range(rows)]
    frame["as_of_month"] = "2025-01"
    frame[LABEL_COLUMN] = (frame["reports_24m"] > 15).astype("int8")
    return frame


# ------------------------------------------------------------------ the two rules


def test_the_rule_returns_only_zero_and_one():
    """It is a rule, not a probability. Reporting it as if it ranked manufacturers would flatter
    it - and its own precision@k is arbitrary among everything it flags because of the ties."""
    scores = reported_recently(fake())
    assert set(np.unique(scores)) <= {0.0, 1.0}


def test_the_rule_flags_exactly_the_recently_reported():
    frame = pd.DataFrame({"reports_6m": [0, 1, 5, 0]})
    assert list(reported_recently(frame)) == [0.0, 1.0, 1.0, 0.0]


def test_the_count_ranking_is_the_column_itself():
    """Baseline 3 has nothing to fit, which is what makes it the do-you-need-a-model test."""
    frame = pd.DataFrame({"reports_24m": [0, 7, 3]})
    assert list(reports_24m_ranking(frame)) == [0.0, 7.0, 3.0]


def test_neither_rule_looks_at_the_training_data():
    train, evaluate_on = fake(seed=1), fake(seed=2)
    scores = score_all(train, evaluate_on)
    assert list(scores["rule: reported in last 6m"]) == list(reported_recently(evaluate_on))
    assert list(scores["ranking: reports in last 24m"]) == list(reports_24m_ranking(evaluate_on))


# ------------------------------------------------------------------ the fitted baseline


def test_scoring_before_fitting_is_refused():
    """Silently scoring with no medians would mean imputing with nothing and ranking on noise."""
    with pytest.raises(RuntimeError, match="fit\\(\\) must run before scoring"):
        LogisticBaseline().score(fake())


def test_the_medians_come_from_training_only():
    """The leak check. Filling an evaluation set's nulls with its own median lets information from
    the evaluation period into its own features - small, invisible, and real."""
    train = fake(seed=1)
    train.loc[:, "assay_share_12m"] = 0.1
    evaluate_on = fake(seed=2)
    evaluate_on.loc[:, "assay_share_12m"] = np.nan

    model = LogisticBaseline().fit(train)
    assert model.medians["assay_share_12m"] == pytest.approx(0.1)

    filled = evaluate_on[list(FEATURE_COLUMNS)].astype("float64").fillna(model.medians)
    assert filled["assay_share_12m"].eq(0.1).all(), "evaluation nulls must take TRAINING's median"


def test_a_column_that_is_entirely_null_in_training_becomes_zero_not_nan():
    """Otherwise the null median survives fillna and reaches the model as NaN, which raises deep
    inside sklearn with a message that says nothing about the data."""
    train = fake(seed=1)
    train.loc[:, "sterility_share_12m"] = np.nan
    model = LogisticBaseline().fit(train)
    scores = model.score(fake(seed=2))
    assert np.isfinite(scores).all()


def test_it_produces_probabilities_not_arbitrary_numbers():
    model = LogisticBaseline().fit(fake(seed=1))
    scores = model.score(fake(seed=2))
    assert ((scores >= 0) & (scores <= 1)).all()


def test_it_learns_the_signal_it_was_given():
    """A baseline that cannot find a planted signal is broken, and would make the bar too easy."""
    train, evaluate_on = fake(seed=1), fake(seed=2)
    scores = LogisticBaseline().fit(train).score(evaluate_on)
    from drugwatch_ml.metrics import roc_auc

    assert roc_auc(evaluate_on[LABEL_COLUMN], scores) > 0.9


def test_the_coefficients_are_comparable_and_ordered_by_size():
    """Only meaningful because the inputs were scaled; without that they rank by unit, not by
    influence."""
    weights = LogisticBaseline().fit(fake()).coefficients()
    assert list(weights.index[:3]) == list(weights.abs().sort_values(ascending=False).index[:3])
    assert set(weights.index) == set(FEATURE_COLUMNS)


def test_the_fit_is_reproducible():
    train, evaluate_on = fake(seed=1), fake(seed=2)
    first = LogisticBaseline(seed=3).fit(train).score(evaluate_on)
    second = LogisticBaseline(seed=3).fit(train).score(evaluate_on)
    assert np.array_equal(first, second)
