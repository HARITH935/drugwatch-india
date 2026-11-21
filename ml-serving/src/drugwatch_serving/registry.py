"""Load the registered model from MLflow, and say exactly which version is answering.

Plan §9 Phase 8 step 4: *"load model version from MLflow"*. A service that silently picks up
whatever is newest cannot be debugged: a score someone disputes has to be traceable to a version,
and that version's own tags carry its limitations (set in Phase 7's `publish`).

So the alias is resolved once, at startup, and the resolved version number plus its limitations
are held in memory and reported by `/health`. If the registry is unreachable the service refuses
to start rather than serving nothing - a prediction API that answers 200 with no model is worse
than one that is plainly down.
"""

import os
from dataclasses import dataclass, field
from typing import Any

import mlflow

MODEL_NAME = "manufacturer-risk"
ALIAS = "production"


@dataclass
class LoadedModel:
    """What the service is serving, and what it must say about it."""

    name: str
    version: str
    run_id: str
    model: Any
    feature_names: tuple[str, ...]
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def limitations(self) -> str:
        """The sentence Phase 7 attached to this version. Served with every explanation."""
        return self.tags.get(
            "limitations",
            "Reflects reporting history, not medicine quality.",
        )

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "version": self.version,
            "run_id": self.run_id,
            "features": len(self.feature_names),
            "test_window": self.tags.get("test_window", "unknown"),
            "test_pr_auc": self.tags.get("test_pr_auc", "unknown"),
            "test_roc_auc": self.tags.get("test_roc_auc", "unknown"),
            "limitations": self.limitations,
        }


def tracking_uri(env: dict[str, str] | None = None) -> str:
    """Inside Docker this is http://mlflow:5000; from the Mac, the published port."""
    source = env if env is not None else dict(os.environ)
    return source.get("MLFLOW_TRACKING_URI", "http://localhost:5050")


def load(name: str = MODEL_NAME, alias: str = ALIAS) -> LoadedModel:
    """Resolve the alias to a concrete version and load it. Raises if anything is missing."""
    mlflow.set_tracking_uri(tracking_uri())
    client = mlflow.MlflowClient()

    # Resolved by alias, not by "latest": a deliberate pointer somebody moved, rather than
    # whatever happened to be registered most recently.
    version = client.get_model_version_by_alias(name, alias)
    booster = mlflow.lightgbm.load_model(f"models:/{name}@{alias}")

    # The feature order comes from the model itself. Taking it from a config file instead is how a
    # service ends up silently feeding `reports_6m` into the `reports_24m` slot.
    feature_names = tuple(getattr(booster, "feature_name_", None) or booster.feature_name())

    return LoadedModel(
        name=name,
        version=version.version,
        run_id=version.run_id,
        model=booster,
        feature_names=feature_names,
        tags=dict(version.tags),
    )
