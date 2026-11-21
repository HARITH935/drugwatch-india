"""SHAP contributions for one served row, reusing Phase 7's approved wording.

The vocabulary, the forbidden-word list and the reporting-history clause all live in
`drugwatch_ml.explain` and are **not** restated here. A second copy of public wording about named
companies is a second thing to keep correct, and the one that drifts is always the copy.

`drugwatch-ml` is a dev dependency of this project, so the container does not get it. The import
is therefore done lazily and its absence is reported as a clear 503 rather than an ImportError
traceback: a container built without the explanation stack can still serve `/predict`.
"""

from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException


def build_explainer(booster) -> Any:
    """A SHAP TreeExplainer, or None if the explanation stack is not installed."""
    try:
        import shap
    except ImportError:
        return None
    return shap.TreeExplainer(booster)


def explain_row(
    explainer: Any, matrix: np.ndarray, feature_names: tuple[str, ...], top: int = 3
) -> tuple[list[dict[str, Any]], list[str]]:
    """The top contributions and the sentences for one row."""
    if explainer is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "this build serves /predict only; SHAP is not installed"},
        )
    try:
        from drugwatch_ml.explain import Contribution, explanation_sentences
    except ImportError as error:
        raise HTTPException(
            status_code=503,
            detail={"error": "the approved explanation wording is not available in this build"},
        ) from error

    frame = pd.DataFrame(matrix, columns=list(feature_names))
    values = explainer.shap_values(frame)
    if isinstance(values, list):
        values = values[1] if len(values) == 2 else values[0]
    row_values = np.asarray(values)[0]

    ranked = sorted(
        (
            Contribution(feature=name, value=float(frame.iloc[0][name]), push=float(push))
            for name, push in zip(feature_names, row_values, strict=True)
        ),
        key=lambda contribution: abs(contribution.push),
        reverse=True,
    )[:top]

    contributions = [
        {
            "feature": contribution.feature,
            "value": None if np.isnan(contribution.value) else round(contribution.value, 4),
            "effect": contribution.direction,
            "push": round(contribution.push, 4),
        }
        for contribution in ranked
    ]
    return contributions, explanation_sentences(ranked)
