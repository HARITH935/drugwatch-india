"""The LightGBM wrapper, and the three things it is deliberately not told."""

import numpy as np
import pandas as pd
import pytest

from drugwatch_ml.features import FEATURE_COLUMNS, LABEL_COLUMN
from drugwatch_ml.model import RiskModel, Settings


def fake(rows: int = 600, seed: int = 0, with_nulls: bool = True) -> pd.DataFrame:
    """The real column set, a learnable signal, and nulls where the mart has them."""
    generator = np.random.default_rng(seed)
    data = {column: generator.random(rows) for column in FEATURE_COLUMNS}
    data["reports_24m"] = generator.integers(0, 30, rows).astype("float64")
    frame = pd.DataFrame(data)
    if with_nulls:
        # A share is null when the window held no findings to divide - absence, not 0%.
        frame.loc[frame["reports_24m"] == 0, "assay_share_12m"] = np.nan
    frame["manufacturer_id"] = [f"m{i % 60}" for i in range(rows)]
    frame["as_of_month"] = "2025-01"
    frame[LABEL_COLUMN] = (frame["reports_24m"] > 15).astype("int8")
    return frame


def test_nulls_are_passed_straight_through():
    """The reason this model needs no imputation. "No reports at all" and "reports, none of them
    an assay failure" are different states, and filling the null would merge them."""
    train = fake(seed=1)
    assert train["assay_share_12m"].isna().any(), "the fixture should contain nulls"
    model = RiskModel().fit(train)
    scores = model.score(fake(seed=2))
    assert np.isfinite(scores).all()


def test_a_frame_that_is_entirely_null_in_one_feature_still_scores():
    train = fake(seed=1)
    train.loc[:, "sterility_share_12m"] = np.nan
    scores = RiskModel().fit(train).score(fake(seed=2))
    assert np.isfinite(scores).all()


def test_scoring_before_fitting_is_refused():
    with pytest.raises(RuntimeError, match="fit\\(\\) must run before scoring"):
        RiskModel().score(fake())


def test_reading_importances_before_fitting_is_refused():
    with pytest.raises(RuntimeError, match="fit\\(\\) must run"):
        RiskModel().importances()


def test_it_produces_probabilities():
    scores = RiskModel().fit(fake(seed=1)).score(fake(seed=2))
    assert ((scores >= 0) & (scores <= 1)).all()


def test_it_learns_a_planted_signal():
    from drugwatch_ml.metrics import roc_auc

    evaluate_on = fake(seed=2)
    scores = RiskModel().fit(fake(seed=1)).score(evaluate_on)
    assert roc_auc(evaluate_on[LABEL_COLUMN], scores) > 0.9


def test_the_fit_is_reproducible():
    """`deterministic=True` plus a fixed seed. Without it two identical runs log different
    numbers and no comparison between settings means anything."""
    train, evaluate_on = fake(seed=1), fake(seed=2)
    first = RiskModel().fit(train).score(evaluate_on)
    second = RiskModel().fit(train).score(evaluate_on)
    assert np.array_equal(first, second)


def test_only_the_declared_features_reach_the_model():
    """The frame carries manufacturer_id, as_of_month and the label. If any of them leaked into
    the matrix the model would be reading its own answer, or a calendar."""
    model = RiskModel().fit(fake())
    assert list(model.model.feature_name_) == list(FEATURE_COLUMNS)
    for forbidden in ("manufacturer_id", "as_of_month", LABEL_COLUMN):
        assert forbidden not in model.model.feature_name_


def test_importances_cover_every_feature_and_the_model_uses_more_than_one():
    importances = RiskModel().fit(fake()).importances()
    assert set(importances.index) == set(FEATURE_COLUMNS)
    assert (importances > 0).sum() > 1


# ------------------------------------------------------------------ settings


def test_bagging_fraction_without_a_frequency_does_nothing():
    """LightGBM silently ignores a bagging fraction below 1 unless bagging_freq is set. The tuner
    derives the frequency for exactly this reason - otherwise a third of the search space would be
    secretly identical to the rest."""
    ignored = Settings(bagging_fraction=0.7, bagging_freq=0).as_params()
    applied = Settings(bagging_fraction=0.7, bagging_freq=1).as_params()
    assert ignored["bagging_freq"] == 0
    assert applied["bagging_freq"] == 1


def test_the_defaults_leave_probabilities_unweighted():
    """scale_pos_weight above 1 lifts ranking and distorts the predicted probability, which §4.3
    shows publicly as a probability. The default must not quietly do that."""
    assert Settings().scale_pos_weight == 1.0


def test_settings_are_fully_described_for_tracking():
    tags = Settings().as_tags()
    assert set(tags) == {
        "n_estimators",
        "learning_rate",
        "num_leaves",
        "min_child_samples",
        "feature_fraction",
        "bagging_fraction",
        "bagging_freq",
        "lambda_l2",
        "scale_pos_weight",
    }
    assert all(isinstance(value, str) for value in tags.values())
