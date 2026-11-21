"""Loading the registered model, and what the service must be able to say about it."""

import pytest

from drugwatch_serving.registry import ALIAS, MODEL_NAME, LoadedModel, tracking_uri


def test_the_tracking_uri_defaults_to_the_published_port():
    assert tracking_uri({}) == "http://localhost:5050"


def test_inside_docker_the_service_name_is_used():
    assert tracking_uri({"MLFLOW_TRACKING_URI": "http://mlflow:5000"}) == "http://mlflow:5000"


def test_the_model_is_resolved_by_alias_not_by_latest():
    """A deliberate pointer somebody moved, rather than whatever was registered most recently."""
    assert ALIAS == "production"
    assert MODEL_NAME == "manufacturer-risk"


def test_limitations_always_have_a_value():
    """They are served with every explanation, so a version registered without the tag must not
    produce an empty caveat."""
    bare = LoadedModel("m", "1", "run", object(), ("a",), tags={})
    assert "reporting history" in bare.limitations.lower()


def test_the_registered_limitations_win_when_present():
    tagged = LoadedModel("m", "1", "run", object(), ("a",), tags={"limitations": "tied with LR"})
    assert tagged.limitations == "tied with LR"


def test_the_description_names_the_version_and_its_caveats():
    """`/health` has to answer "which model is this and what is wrong with it" in one request."""
    loaded = LoadedModel(
        "manufacturer-risk",
        "1",
        "abc",
        object(),
        tuple(f"f{i}" for i in range(28)),
        tags={"test_pr_auc": "0.3846", "test_window": "2025-04..2026-03"},
    )
    described = loaded.describe()
    assert described["version"] == "1"
    assert described["features"] == 28
    assert described["test_pr_auc"] == "0.3846"
    assert described["test_window"] == "2025-04..2026-03"
    assert "limitations" in described


@pytest.mark.integration
def test_loading_the_real_registered_model():
    from drugwatch_serving.registry import load

    try:
        loaded = load()
    except Exception as error:  # noqa: BLE001 - any failure here means "no registry available"
        pytest.skip(f"no MLflow registry with a registered model: {error}")
    assert len(loaded.feature_names) == 28
    assert loaded.version.isdigit()
    # Phase 7 attached these; the service relies on them being there.
    assert "test_pr_auc" in loaded.tags
    assert "logistic regression" in loaded.limitations
