"""The prediction service: `/health`, `/predict`, `/explain`.

Plan §9 Phase 8 steps 3-4. Three design choices worth stating, because each is a constraint rather
than a preference:

**1. The service never touches the warehouse.** It takes features in the request body and returns
a score. Phase 9's Spring Boot API reads `gold` (plan §5) and posts what it read. A service that
queried Postgres itself would need credentials, would be slow in a way nobody could cache, and
would couple the model's uptime to the warehouse's.

**2. `/predict` answers from ONNX, `/explain` from the original model** - and the two are checked
against each other at startup. ONNX is the portable fast path; SHAP needs the tree structure ONNX
discards. Serving a score from one and an explanation of the other would let a reader see "14%"
beside an explanation of a different number, so startup refuses if they disagree.

**3. A missing feature is an error, not a zero.** Several features are legitimately null - a share
is null when the window held no findings to divide - so null is a *value* here and the model was
trained to read it. Silently filling an absent field with 0 would mean answering a different
question from the one asked.
"""

import contextlib
import os
from typing import Annotated, Any

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from drugwatch_serving import onnx_export, registry

# What the service is holding. Populated at startup and never reassigned afterwards.
STATE: dict[str, Any] = {}

# Largest tolerated gap between the ONNX path and the original model, at startup. The same
# threshold the export uses: half the smallest unit any reader will ever see.
STARTUP_TOLERANCE = onnx_export.DISPLAY_TOLERANCE


class Rows(BaseModel):
    """A batch of manufacturer-months to score."""

    rows: list[dict[str, float | None]] = Field(
        ..., min_length=1, max_length=5000, description="one object per manufacturer-month"
    )


class SingleRow(BaseModel):
    """One manufacturer-month to explain."""

    features: dict[str, float | None]
    top: Annotated[int, Field(ge=1, le=10)] = 3


def matrix_from(rows: list[dict[str, float | None]], feature_names: tuple[str, ...]) -> np.ndarray:
    """Build the model's input matrix, refusing anything that is not exactly the right shape.

    Column ORDER comes from the model, not from the request: JSON objects have no meaningful order
    and a caller that happened to serialise its fields differently would otherwise have every
    value silently shifted into the wrong feature.
    """
    missing = sorted(set(feature_names) - set(rows[0]))
    unexpected = sorted(set(rows[0]) - set(feature_names))
    if missing or unexpected:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "the request does not carry exactly the model's features",
                "missing": missing,
                "unexpected": unexpected,
                "expected_count": len(feature_names),
            },
        )
    matrix = np.empty((len(rows), len(feature_names)), dtype="float64")
    for index, row in enumerate(rows):
        if set(row) != set(feature_names):
            raise HTTPException(
                status_code=422,
                detail={"error": f"row {index} has a different feature set from row 0"},
            )
        # None becomes NaN, which is what the model was trained to read as "no reports to divide".
        matrix[index] = [np.nan if row[name] is None else row[name] for name in feature_names]
    return matrix


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Phase 12 (ADR 0021): the Hugging Face Space this service runs on is reachable over the
    public internet even set to "private" visibility - that setting only gates the browser UI,
    not calls from another server. So the one caller meant to reach this service (Phase 9's
    Spring Boot API) proves it with a shared bearer token, checked here rather than left to the
    platform.

    Unset locally - `docker-compose.yml` sets nothing - so local dev and the existing test suite
    are unaffected; this only bites once `RISK_API_TOKEN` is set, which happens on the Space.
    """
    expected = os.environ.get("RISK_API_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the model, export it to ONNX, and prove the two paths agree before serving anything."""
    loaded = registry.load()
    STATE["loaded"] = loaded

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model.onnx"
        onnx_export.convert(loaded.model, len(loaded.feature_names), path)
        # The session keeps the graph in memory, so the file is not needed after this.
        STATE["session"] = onnx_export.session(path)

    # Agreement is checked on the model's own training example rather than on random numbers,
    # which would exercise leaves no manufacturer ever reaches.
    probe = np.nan_to_num(np.zeros((1, len(loaded.feature_names))), nan=0.0)
    original = float(loaded.model.predict_proba(probe)[:, 1][0])
    converted = float(onnx_export.predict(STATE["session"], probe)[0])
    if abs(original - converted) > STARTUP_TOLERANCE:
        raise RuntimeError(
            f"the ONNX export disagrees with the model it came from ({original:.6f} vs"
            f" {converted:.6f}). Refusing to serve: /predict and /explain would describe"
            " different numbers."
        )
    STATE["startup_agreement"] = abs(original - converted)

    from drugwatch_serving.explanations import build_explainer, explain_row

    STATE["explainer"] = build_explainer(loaded.model)

    # Warm the explainer with one throwaway row. Measured: SHAP's first call costs ~77ms against
    # ~4ms for every call after it, so without this the first reader to ask for an explanation
    # pays a cost nobody else does - and it showed up as a p99 of 558ms in an otherwise 5.6ms
    # endpoint. Doing it here puts the cost inside container startup, which the healthcheck's
    # start_period already covers.
    if STATE["explainer"] is not None:
        with contextlib.suppress(Exception):
            explain_row(STATE["explainer"], probe, loaded.feature_names, top=1)

    yield
    STATE.clear()


app = FastAPI(
    title="DrugWatch India - manufacturer risk score",
    description=(
        "Estimates the probability that a manufacturer already present in the CDSCO archive is"
        " named in an alert in the next 6 months. Reflects reporting history, not medicine"
        " quality. See docs/model-card.md."
    ),
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_token)],
)


@app.get("/health")
def health() -> dict[str, Any]:
    """Which model is answering, what it scored, and what is wrong with it.

    Deliberately more than `{"status": "ok"}`: a disputed score has to be traceable to a version,
    and the limitations are part of what this service serves.
    """
    loaded = STATE.get("loaded")
    if loaded is None:
        raise HTTPException(status_code=503, detail={"status": "no model loaded"})
    return {
        "status": "ok",
        "onnx_agreement": STATE.get("startup_agreement"),
        **loaded.describe(),
    }


@app.post("/predict")
def predict(request: Rows) -> dict[str, Any]:
    """Scores for a batch of manufacturer-months, answered from the ONNX model."""
    loaded = STATE["loaded"]
    matrix = matrix_from(request.rows, loaded.feature_names)
    scores = onnx_export.predict(STATE["session"], matrix)
    return {
        "scores": [round(float(score), 6) for score in scores],
        "model": {"name": loaded.name, "version": loaded.version},
        "means": "probability of being named in a CDSCO alert in the next 6 months",
        "limitations": loaded.limitations,
    }


@app.post("/explain")
def explain(request: SingleRow) -> dict[str, Any]:
    """One score with the features that moved it, in neutral wording.

    The score returned is the **ONNX** one, so it is the same number `/predict` gives for the same
    row. The contributions come from SHAP over the original model, which is the only way to get
    them - startup has already checked the two paths agree.
    """
    loaded = STATE["loaded"]
    matrix = matrix_from([request.features], loaded.feature_names)
    score = float(onnx_export.predict(STATE["session"], matrix)[0])

    from drugwatch_serving.explanations import explain_row

    contributions, sentences = explain_row(
        STATE["explainer"], matrix, loaded.feature_names, top=request.top
    )
    return {
        "score": round(score, 6),
        "model": {"name": loaded.name, "version": loaded.version},
        "contributions": contributions,
        "explanation": sentences,
        "limitations": loaded.limitations,
    }
