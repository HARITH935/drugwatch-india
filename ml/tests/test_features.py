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
