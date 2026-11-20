"""The feature reader: its settings, its guards, and the columns it will and will not hand over."""

import pandas as pd
import pytest

from drugwatch_ml.features import (
    FEATURE_COLUMNS,
    KEY_COLUMNS,
    LABEL_COLUMN,
    check_columns,
    connection_info,
    load_features,
)

# Features that drift with calendar time between 0.5 and 0.7, each kept for a stated reason.
# Anything stronger than 0.7 is rejected outright by the test below.
KNOWN_DRIFTERS = {
    # -0.534, measured 2026-11-20. Real and not a bug: state drug-testing laboratories grew
    # relative to CDSCO's central ones across the archive, so the central share of any company's
    # reports falls over time. It is still a genuine company-level feature - which laboratories
    # tested THIS company's products - so it is kept rather than dropped, and the model card notes
    # that SHAP should be checked for over-reliance on it.
    "central_lab_share_12m",
}


def test_the_password_is_never_defaulted():
    with pytest.raises(KeyError, match="POSTGRES_PASSWORD"):
        connection_info({"POSTGRES_HOST": "localhost"})


def test_defaults_match_docker_compose():
    info = connection_info({"POSTGRES_PASSWORD": "secret"})
    assert (info["host"], info["port"]) == ("localhost", 5433)


def test_the_label_is_not_a_feature():
    """The one mistake that would make every metric meaningless."""
    assert LABEL_COLUMN not in FEATURE_COLUMNS
    assert "label_window_complete" not in FEATURE_COLUMNS


def test_the_keys_are_not_features():
    """`as_of_month` as a feature would let the model learn "later months are riskier" from the
    archive growing, which is a fact about CDSCO's publishing, not about any manufacturer."""
    assert not set(KEY_COLUMNS) & set(FEATURE_COLUMNS)
    assert "manufacturer_id" not in FEATURE_COLUMNS


def test_no_feature_is_listed_twice():
    assert len(set(FEATURE_COLUMNS)) == len(FEATURE_COLUMNS)


def test_check_columns_rejects_a_missing_feature():
    """A renamed mart column must stop the run, not arrive as a column of nulls."""
    frame = pd.DataFrame(columns=[*KEY_COLUMNS, *FEATURE_COLUMNS[:-1], LABEL_COLUMN])
    with pytest.raises(ValueError, match="missing expected column"):
        check_columns(frame)


def test_check_columns_rejects_a_missing_label():
    frame = pd.DataFrame(columns=[*KEY_COLUMNS, *FEATURE_COLUMNS])
    with pytest.raises(ValueError, match="label column"):
        check_columns(frame)


@pytest.mark.integration
def test_the_feature_list_matches_the_live_mart(gold_available):
    """Pins this code to the warehouse. A feature column added to the mart later has to be added
    here deliberately - it must not become a model input by existing."""
    from drugwatch_ml.features import query

    live = query("select * from gold.mart_ml_features limit 0")
    expected = {*KEY_COLUMNS, *FEATURE_COLUMNS, LABEL_COLUMN, "label_window_complete"}
    assert set(live.columns) == expected, (
        f"the mart changed. only in the mart: {set(live.columns) - expected}; "
        f"only in this code: {expected - set(live.columns)}"
    )


@pytest.mark.integration
def test_loading_gives_numeric_features_and_a_complete_label(gold_available):
    frame = load_features()
    check_columns(frame)
    assert len(frame) > 10_000
    assert frame["label_window_complete"].all()
    assert frame[LABEL_COLUMN].isin((0, 1)).all()
    for column in FEATURE_COLUMNS:
        assert frame[column].dtype.kind in "fiu", f"{column} is {frame[column].dtype}"


@pytest.mark.integration
def test_the_unlabelled_rows_are_available_but_separate(gold_available):
    """Scoring a manufacturer today uses exactly the rows training must never see: features known
    now, outcome not knowable yet. Both have to be reachable, and never mixed by accident."""
    labelled = load_features()
    everything = load_features(labelled_only=False)
    assert len(everything) > len(labelled)
    unknown = everything[~everything["label_window_complete"]]
    assert unknown[LABEL_COLUMN].isna().all(), "an unknowable future must stay null, never 0"


@pytest.mark.integration
def test_no_feature_is_a_constant(gold_available):
    """A constant feature is the worst kind of broken one: the model trains on it without
    complaint and SHAP calls it unimportant, which is true and tells nobody that it is empty.
    This is how a mis-written filter was caught while building the drug-class shares - it counted
    zero of 1,382 unclassified findings and every range check still passed."""
    frame = load_features()
    constant = [c for c in FEATURE_COLUMNS if frame[c].nunique(dropna=True) <= 1]
    assert constant == [], f"these features never vary: {constant}"


@pytest.mark.integration
def test_no_feature_is_a_calendar(gold_available):
    """The leak that survives a correct time split.

    A feature that tracks the cutoff lets the model learn "later months are riskier", which is a
    fact about how much CDSCO published rather than about any manufacturer - and it extrapolates
    wrongly, because the test period is strictly later than training. Tree models cannot
    extrapolate at all, so such a feature does not even fail loudly: it just saturates, and then
    SHAP reports a calendar as a risk factor.

    This is why the archive's testing volume enters only as a ratio. Measured 2026-11-20: the raw
    12-month archive volume correlates **0.855** with calendar time, while
    `share_of_archive_reports_12m` correlates **-0.180**.

    The threshold is 0.7 - strong proxies only - and `KNOWN_DRIFTERS` pins the one feature in
    between, so a new drifter cannot appear unnoticed.
    """
    frame = load_features()
    cutoff_index = frame["as_of_month"].map(lambda m: int(m[:4]) * 12 + int(m[5:7])).astype(float)

    correlations = {}
    for column in FEATURE_COLUMNS:
        values = frame[column].astype("float64")
        if values.nunique(dropna=True) <= 1:
            continue
        correlations[column] = float(values.corr(cutoff_index))

    strong = {c: round(r, 3) for c, r in correlations.items() if abs(r) > 0.7}
    assert not strong, f"these features are calendars, not company features: {strong}"

    moderate = {c: round(r, 3) for c, r in correlations.items() if 0.5 < abs(r) <= 0.7}
    assert set(moderate) == set(KNOWN_DRIFTERS), (
        f"the set of features that drift with time changed. now: {moderate}, "
        f"documented: {KNOWN_DRIFTERS}. If the new one is a genuine company feature, add it with "
        "its reason; if it is a clock in disguise, it does not belong in the matrix."
    )
