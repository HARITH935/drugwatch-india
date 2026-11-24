"""Phase 10 step 6: load the fallback's adapter from MLflow, not a local path.

The same idiom `ml-serving/registry.py` uses for the risk model: resolve a named, aliased
("production") registered model to a concrete version at load time, so a pipeline task on any
host - this Mac, CI, Phase 12's eventual VM - gets whichever version is currently tagged, instead
of one hand-typed `../data/llm-training/runs/<run>/` path that only ever existed on the machine
that trained it.

The one real difference from the risk model: there is no `mlflow.lightgbm.load_model`-style
one-call loader for a LoRA adapter, because MLflow has no PEFT/LoRA flavour. `publish_run.py`
logged (and now registers) the adapter as plain files, so this downloads them to a local
directory (`mlflow.artifacts.download_artifacts`) and loads the base model plus the adapter on
top of it exactly as `evaluate.py` does from a local run - the registry only changes WHERE the
files came from, not how they're loaded once they're on disk.
"""

import os
from dataclasses import dataclass, field
from typing import Any

import mlflow
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, PreTrainedTokenizerBase

from drugwatch_llm.publish_run import MODEL_NAME, PRODUCTION_ALIAS
from drugwatch_llm.train import MODEL_ID


@dataclass
class LoadedAdapter:
    """What the fallback is running, for logs and provenance - the Airflow task log is the only
    record of which version actually touched a given month's bronze, so this is worth printing,
    not just holding."""

    name: str
    version: str
    run_id: str
    base_model_id: str
    model: Any
    tokenizer: PreTrainedTokenizerBase
    tags: dict[str, str] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "version": self.version,
            "run_id": self.run_id,
            "base_model_id": self.base_model_id,
        }


def tracking_uri(env: dict[str, str] | None = None) -> str:
    """Same default as `tracking.py`/`ml-serving`'s: the published port from the Mac, or
    `http://mlflow:5000` inside Docker when `MLFLOW_TRACKING_URI` is set there."""
    source = env if env is not None else dict(os.environ)
    return source.get("MLFLOW_TRACKING_URI", "http://localhost:5050")


def load_from_dir(
    local_dir: str, device: str, base_model_id: str = MODEL_ID, **identity: str
) -> LoadedAdapter:
    """Load the base model plus an adapter already sitting on local disk - no MLflow call at
    all. Split out of `load` so a Mac whose 8 GB is already spent on Docker's own stack can
    download the adapter once (while MLflow is up) and then run inference with MLflow stopped,
    the same "the two steps don't both need to be up at once" idea ADR 0019 already applies to
    `train.py` vs `publish_run.py`. `identity` fills in whatever `load` would otherwise have
    read from the registry (name/version/run_id), for a caller that already knows it."""
    tokenizer = AutoTokenizer.from_pretrained(base_model_id)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(base_model_id, dtype=torch.bfloat16).to(device)
    # Inference only - the backward-pass MPS cliff that sent training to Colab/Kaggle (ADR 0019)
    # does not apply to a forward pass, already measured fine on a Mac at step 0.
    model = PeftModel.from_pretrained(base, local_dir)
    model.eval()
    return LoadedAdapter(
        name=identity.get("name", "unknown"),
        version=identity.get("version", "unknown"),
        run_id=identity.get("run_id", "unknown"),
        base_model_id=base_model_id,
        model=model,
        tokenizer=tokenizer,
    )


def load(device: str, name: str = MODEL_NAME, alias: str = PRODUCTION_ALIAS) -> LoadedAdapter:
    """Resolve the alias to a concrete version, download its adapter files, and load the base
    model plus the adapter on top of it. Raises if the registry is unreachable or the alias
    isn't set - a fallback that silently skips every row because it couldn't load is worse than
    one that fails the task loudly (the same reasoning `ml-serving/registry.py` gives)."""
    mlflow.set_tracking_uri(tracking_uri())
    client = mlflow.MlflowClient()
    version = client.get_model_version_by_alias(name, alias)
    base_model_id = version.tags.get("base_model_id", MODEL_ID)
    local_dir = mlflow.artifacts.download_artifacts(artifact_uri=f"models:/{name}@{alias}")
    loaded = load_from_dir(
        local_dir, device, base_model_id, name=name, version=version.version, run_id=version.run_id
    )
    loaded.tags = dict(version.tags)
    return loaded
