"""Load the registered model from MLflow, and say exactly which version is answering.

Plan §9 Phase 8 step 4: *"load model version from MLflow"*. A service that silently picks up
whatever is newest cannot be debugged: a score someone disputes has to be traceable to a version,
and that version's own tags carry its limitations (set in Phase 7's `publish`).

So the alias is resolved once, at startup, and the resolved version number plus its limitations
are held in memory and reported by `/health`. If the registry is unreachable the service refuses
to start rather than serving nothing - a prediction API that answers 200 with no model is worse
than one that is plainly down.

**Phase 12 (ADR 0021) does not deploy MLflow in production** - the Hugging Face Space the risk
service runs on has no registry to call. `export_bundle()` runs once on the Mac, while the real
MLflow is up, and writes everything `load()` needs into a plain folder: the model itself (via
MLflow's own on-disk format, so no tracking server is needed to read it back) plus the version,
run_id and tags `load()` would otherwise have asked the registry for. `MODEL_SOURCE=local` then
loads that folder instead of calling MLflow - same `LoadedModel`, same guarantees, zero network.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
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


def model_source(env: dict[str, str] | None = None) -> str:
    """ "mlflow" (default, local dev) or "local" (Phase 12: no registry to call)."""
    source = env if env is not None else dict(os.environ)
    return source.get("MODEL_SOURCE", "mlflow")


def load(name: str = MODEL_NAME, alias: str = ALIAS) -> LoadedModel:
    """Resolve the alias to a concrete version and load it. Raises if anything is missing."""
    if model_source() == "local":
        return load_local(Path(os.environ.get("MODEL_BUNDLE_PATH", "/app/model-bundle")))

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


def export_bundle(bundle_dir: Path, name: str = MODEL_NAME, alias: str = ALIAS) -> None:
    """Run once on the Mac, with the real MLflow up. Writes a self-contained folder that
    `load_local()` can read with no tracking server - what `export_bundle` + `load_local`
    together replace is exactly what `load()`'s MLflow branch above does over the network."""
    mlflow.set_tracking_uri(tracking_uri())
    client = mlflow.MlflowClient()
    version = client.get_model_version_by_alias(name, alias)
    booster = mlflow.lightgbm.load_model(f"models:/{name}@{alias}")

    bundle_dir.mkdir(parents=True, exist_ok=True)
    model_dir = bundle_dir / "model"
    if model_dir.exists():
        import shutil

        shutil.rmtree(model_dir)
    # MLflow's own on-disk flavor: load_model() below reads it back with a file:// URI, no
    # tracking server involved - the registry is only needed to resolve the alias, which already
    # happened above.
    mlflow.lightgbm.save_model(booster, str(model_dir))

    metadata = {
        "name": name,
        "version": version.version,
        "run_id": version.run_id,
        "tags": dict(version.tags),
    }
    (bundle_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))


def load_local(bundle_dir: Path) -> LoadedModel:
    """The production path (`MODEL_SOURCE=local`): read what `export_bundle()` wrote, with no
    MLflow tracking server reachable - there is none on the Hugging Face Space (ADR 0021)."""
    metadata = json.loads((bundle_dir / "metadata.json").read_text())
    booster = mlflow.lightgbm.load_model(f"file://{bundle_dir / 'model'}")
    feature_names = tuple(getattr(booster, "feature_name_", None) or booster.feature_name())

    return LoadedModel(
        name=metadata["name"],
        version=metadata["version"],
        run_id=metadata["run_id"],
        model=booster,
        feature_names=feature_names,
        tags=metadata["tags"],
    )
