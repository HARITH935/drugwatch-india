"""The service's contract: what it answers, and what it refuses.

The refusals matter more than the happy path here. A prediction API that quietly accepts a
half-filled request answers a different question from the one asked, and nothing in the response
says so.
"""

import numpy as np
import pytest
from fastapi import HTTPException

from drugwatch_serving.app import matrix_from

NAMES = ("reports_6m", "reports_24m", "assay_share_12m")


# ------------------------------------------------------------------ input validation


def test_the_column_order_comes_from_the_model_not_the_request():
    """JSON objects have no meaningful order. A caller that serialised its fields differently
    would otherwise have every value shifted into the wrong feature - which would still return
    200 and a plausible-looking score."""
    forward = matrix_from([{"reports_6m": 1.0, "reports_24m": 9.0, "assay_share_12m": 0.5}], NAMES)
    shuffled = matrix_from([{"assay_share_12m": 0.5, "reports_24m": 9.0, "reports_6m": 1.0}], NAMES)
    assert np.array_equal(forward, shuffled)
    assert list(forward[0]) == [1.0, 9.0, 0.5]


def test_a_missing_feature_is_refused_and_named():
    """Not filled with zero: several features are legitimately null, so null is a value the model
    was trained to read, and absent means the caller has a bug."""
    with pytest.raises(HTTPException) as raised:
        matrix_from([{"reports_6m": 1.0}], NAMES)
    assert raised.value.status_code == 422
    assert raised.value.detail["missing"] == ["assay_share_12m", "reports_24m"]


def test_an_unexpected_feature_is_refused_rather_than_ignored():
    """Ignoring it would hide a caller sending `reports_12m` when the model wants `reports_24m`."""
    with pytest.raises(HTTPException) as raised:
        matrix_from([{**dict.fromkeys(NAMES, 0.0), "invented": 1.0}], NAMES)
    assert raised.value.detail["unexpected"] == ["invented"]


def test_null_becomes_nan_because_null_is_a_real_value_here():
    """A share is null when the window held no findings to divide. The model learned which side of
    a split that belongs on, so it must arrive as NaN and not as 0."""
    matrix = matrix_from([{"reports_6m": 0.0, "reports_24m": 0.0, "assay_share_12m": None}], NAMES)
    assert np.isnan(matrix[0][2])
    assert matrix[0][0] == 0.0


def test_rows_must_all_carry_the_same_features():
    """A batch where row 5 is missing a field would otherwise be scored against a shifted
    matrix."""
    rows = [dict.fromkeys(NAMES, 0.0), {"reports_6m": 1.0, "reports_24m": 2.0}]
    with pytest.raises(HTTPException) as raised:
        matrix_from(rows, NAMES)
    assert "row 1" in raised.value.detail["error"]


# ------------------------------------------------------------------ the live service


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from drugwatch_serving.app import app

    try:
        with TestClient(app) as started:
            yield started
    except Exception as error:  # noqa: BLE001 - no registry means these tests cannot run
        pytest.skip(f"service could not start (needs MLflow with a registered model): {error}")


def feature_row(client) -> dict[str, float | None]:
    names = client.get("/health").json()["features"]
    from drugwatch_serving.app import STATE

    row = dict.fromkeys(STATE["loaded"].feature_names, 0.0)
    assert len(row) == names
    row["reports_24m"] = 19.0
    row["months_since_last_report"] = 0.0
    return row


@pytest.mark.integration
def test_no_token_required_when_risk_api_token_is_unset(client, monkeypatch):
    """Local dev (docker-compose.yml) sets nothing, so the existing test suite and every
    local curl must keep working exactly as before this step."""
    monkeypatch.delenv("RISK_API_TOKEN", raising=False)
    assert client.get("/health").status_code == 200


@pytest.mark.integration
def test_health_refuses_without_the_token_once_one_is_set(client, monkeypatch):
    monkeypatch.setenv("RISK_API_TOKEN", "the-real-secret")
    response = client.get("/health")
    assert response.status_code == 401


@pytest.mark.integration
def test_health_refuses_the_wrong_token(client, monkeypatch):
    monkeypatch.setenv("RISK_API_TOKEN", "the-real-secret")
    response = client.get("/health", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


@pytest.mark.integration
def test_health_answers_with_the_right_token(client, monkeypatch):
    monkeypatch.setenv("RISK_API_TOKEN", "the-real-secret")
    response = client.get("/health", headers={"Authorization": "Bearer the-real-secret"})
    assert response.status_code == 200


@pytest.mark.integration
def test_health_names_the_version_and_its_limitations(client):
    """A disputed score has to be traceable to a version, and the caveat is part of what is
    served - so `/health` returns more than {"status": "ok"}."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"].isdigit()
    assert "logistic regression" in body["limitations"]
    assert body["test_window"] == "2025-04..2026-03"


@pytest.mark.integration
def test_the_onnx_and_original_paths_agree_at_startup(client):
    """Startup refuses to serve if they do not: /predict answers from ONNX and /explain computes
    SHAP over the original model, so a gap would show a reader one number beside an explanation
    of another."""
    assert client.get("/health").json()["onnx_agreement"] < 5e-4


@pytest.mark.integration
def test_predict_and_explain_return_the_same_score(client):
    """The property that startup check exists to protect, verified on a real request."""
    row = feature_row(client)
    predicted = client.post("/predict", json={"rows": [row]}).json()["scores"][0]
    explained = client.post("/explain", json={"features": row}).json()["score"]
    assert predicted == explained


@pytest.mark.integration
def test_predict_scores_a_batch(client):
    row = feature_row(client)
    quiet = dict.fromkeys(row, 0.0)
    body = client.post("/predict", json={"rows": [row, quiet]}).json()
    assert len(body["scores"]) == 2
    assert all(0.0 <= score <= 1.0 for score in body["scores"])
    assert body["scores"][0] > body["scores"][1], "19 reported batches should outrank none"


@pytest.mark.integration
def test_every_prediction_response_carries_the_caveat(client):
    """CLAUDE.md §6: the reporting-history limitation travels with the number, not with the page
    that happens to display it."""
    row = feature_row(client)
    for path, payload in (("/predict", {"rows": [row]}), ("/explain", {"features": row})):
        body = client.post(path, json=payload).json()
        assert "limitations" in body
        assert body["limitations"]


@pytest.mark.integration
def test_explain_returns_neutral_sentences_and_the_history_clause(client):
    from drugwatch_ml.explain import FORBIDDEN, HISTORY_CLAUSE

    body = client.post("/explain", json={"features": feature_row(client)}).json()
    assert body["explanation"][-1] == HISTORY_CLAUSE
    text = " ".join(body["explanation"]).lower()
    for word in FORBIDDEN:
        assert word not in text


@pytest.mark.integration
def test_explain_reports_its_contributions_with_directions(client):
    body = client.post("/explain", json={"features": feature_row(client), "top": 5}).json()
    assert len(body["contributions"]) == 5
    pushes = [abs(contribution["push"]) for contribution in body["contributions"]]
    assert pushes == sorted(pushes, reverse=True)
    assert all(c["effect"] in ("raises", "lowers") for c in body["contributions"])


@pytest.mark.integration
def test_a_bad_request_is_a_422_with_the_detail(client):
    response = client.post("/predict", json={"rows": [{"reports_24m": 1.0}]})
    assert response.status_code == 422
    assert len(response.json()["detail"]["missing"]) == 27


@pytest.mark.integration
def test_an_empty_batch_is_refused(client):
    assert client.post("/predict", json={"rows": []}).status_code == 422
