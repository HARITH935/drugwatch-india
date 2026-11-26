"""Loading the registered model, and what the service must be able to say about it."""

import pytest

from drugwatch_serving.registry import (
    ALIAS,
    MODEL_NAME,
    LoadedModel,
    export_bundle,
    load,
    load_local,
    model_source,
    tracking_uri,
)


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


def test_model_source_defaults_to_mlflow():
    assert model_source({}) == "mlflow"


def test_model_source_switches_to_local_for_phase_12():
    assert model_source({"MODEL_SOURCE": "local"}) == "local"


@pytest.mark.integration
def test_export_bundle_then_load_local_round_trips_the_registered_model(tmp_path):
    """What `export_model_bundle.py` does on the Mac, and what the Space does at startup -
    proven to agree without a tracking server in the loop for the second half."""
    try:
        export_bundle(tmp_path)
    except Exception as error:  # noqa: BLE001 - any failure here means "no registry available"
        pytest.skip(f"no MLflow registry with a registered model: {error}")

    from_mlflow = load()
    from_bundle = load_local(tmp_path)

    # Proves load_local() is not just "returns something" - it is the same version, the same
    # tags, and (crucially) the model itself scores identically with no network involved.
    assert from_bundle.version == from_mlflow.version
    assert from_bundle.run_id == from_mlflow.run_id
    assert from_bundle.tags == from_mlflow.tags
    assert from_bundle.feature_names == from_mlflow.feature_names

    import numpy as np

    probe = np.zeros((1, len(from_bundle.feature_names)))
    bundle_score = from_bundle.model.predict_proba(probe)[:, 1][0]
    mlflow_score = from_mlflow.model.predict_proba(probe)[:, 1][0]
    assert bundle_score == pytest.approx(mlflow_score)


def test_load_dispatches_to_load_local_when_model_source_is_local(tmp_path, monkeypatch):
    """`load()` itself (not just `load_local()`) has to honour the env switch - this is what
    `lifespan()` actually calls, so a passing `load_local` test alone would not prove the wiring."""
    from drugwatch_serving import registry

    monkeypatch.setenv("MODEL_SOURCE", "local")
    monkeypatch.setenv("MODEL_BUNDLE_PATH", str(tmp_path))
    calls = []
    monkeypatch.setattr(registry, "load_local", lambda path: calls.append(path) or "sentinel")

    assert registry.load() == "sentinel"
    assert calls == [tmp_path]


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
