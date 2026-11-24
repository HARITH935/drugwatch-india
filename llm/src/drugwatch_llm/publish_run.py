"""Phase 10 step 4's lightweight half: log a finished training run to MLflow.

No model is loaded here - this only reads a run directory (`adapter/` + `run_info.json`,
written by `train.py` on the Mac or downloaded from the Colab notebook) and talks to MLflow. That
split is deliberate: `train.py` needs the memory a model plus gradients plus an optimizer's state
takes and competes with Docker's resident VM for the same 8 GB (ADR 0019's amendments); this script
needs neither, so it is the one that is allowed to need Docker up.

Step 6 adds REGISTRATION (plan §9 Phase 10 step 6: a fallback the pipeline can actually load),
the same idiom `ml/publish.py` uses for the risk model: a named registered model
(`MODEL_NAME`) with a `"production"` alias that `registry.py` resolves at pipeline-run time,
so a fallback task on any host - this Mac, CI, Phase 12's eventual VM - loads whichever version
is currently tagged, rather than one hardcoded local run directory. `mlflow.log_model`'s
framework flavours (as the risk model uses for LightGBM) have no PEFT/LoRA flavour to match, so
this registers the plain artifact directory already logged by `publish()` with the generic
`mlflow.register_model`, exactly as `log_artifacts` already uploads it as plain files.

Run (from llm/, Docker up, after a run exists in ../data/llm-training/runs/<name>/ - unzip a
Colab download there first if that's where it trained):
    uv run --env-file ../.env python -m drugwatch_llm.publish_run <run_name>

Or register an already-logged run again (e.g. one published before step 6 added registration),
with no new logging and no model loaded:
    uv run --env-file ../.env python -m drugwatch_llm.publish_run --register-existing <run_id>
"""

import argparse
import json
from pathlib import Path

import mlflow

from drugwatch_llm.tracking import configure, start_run

RUN_DIR = Path("../data/llm-training/runs")
MODEL_NAME = "drugwatch-extraction-fallback"
PRODUCTION_ALIAS = "production"


def load_run(run_name: str) -> tuple[dict, Path]:
    run_dir = RUN_DIR / run_name
    info_path = run_dir / "run_info.json"
    adapter_dir = run_dir / "adapter"
    if not info_path.exists():
        raise FileNotFoundError(f"{info_path} not found - did training actually finish?")
    if not adapter_dir.exists():
        raise FileNotFoundError(f"{adapter_dir} not found - the adapter wasn't saved there")
    return json.loads(info_path.read_text()), adapter_dir


def register(run_id: str, model_id: str = "unknown") -> str:
    """Register an already-logged run's `adapter/` artifact as a new version of `MODEL_NAME`,
    alias it `"production"`, and tag it with what it is. Returns the new version number.

    Takes an MLflow run id, not a local run name: the artifact only needs to already be in
    MLflow (via `publish`, or any earlier publish before this function existed), not on this
    disk - the whole point of registering it is that a later host won't have that directory."""
    client = mlflow.MlflowClient()
    # NOT mlflow.register_model(): MLflow 3's version of it requires a "logged model" entity
    # (mlflow.log_model's own kind of record), which log_artifacts (a plain directory of files,
    # the adapter's actual shape - no PEFT/LoRA flavour exists to log it any other way) never
    # creates. create_model_version is the lower-level call it wraps, and accepts a plain
    # runs:/ artifact path directly - the same thing register_model itself did before MLflow 3.
    try:
        client.create_registered_model(MODEL_NAME)
    except mlflow.exceptions.RestException as error:
        if "RESOURCE_ALREADY_EXISTS" not in str(error):
            raise
    version = client.create_model_version(
        name=MODEL_NAME, source=f"runs:/{run_id}/adapter", run_id=run_id
    ).version
    client.set_registered_model_alias(MODEL_NAME, PRODUCTION_ALIAS, version)
    client.set_model_version_tag(MODEL_NAME, version, "base_model_id", model_id)
    client.set_model_version_tag(MODEL_NAME, version, "source_run_id", run_id)
    return version


def publish(run_name: str, info: dict, adapter_dir: Path) -> tuple[str, str]:
    with start_run(run_name, trained_on=info.get("device", "unknown")) as run:
        mlflow.log_params(
            {
                "model_id": info["model_id"],
                "examples": info["examples"],
                "dropped_examples": info["dropped_examples"],
                "epochs": info["training_args"]["epochs"],
                "grad_accum": info["training_args"]["grad_accum"],
                "lr": info["training_args"]["lr"],
                "lora_r": info["lora_config"]["r"],
                "lora_alpha": info["lora_config"]["lora_alpha"],
                "lora_target_modules": ",".join(info["lora_config"]["target_modules"]),
            }
        )
        mlflow.log_metrics(
            {
                "final_loss": info["final_loss"],
                "mean_loss": info["mean_loss"],
                "elapsed_seconds": info["elapsed_seconds"],
                "seconds_per_example": info["seconds_per_example"],
            }
        )
        # The adapter is a few MB of LoRA weights, not the base model - cheap to upload even
        # over the tracking server's HTTP proxy to RustFS.
        mlflow.log_artifacts(str(adapter_dir), artifact_path="adapter")
        run_id = run.info.run_id
    # Outside the `with`: registration reads the run that was just closed, the same ordering
    # `ml/publish.py` uses for the risk model (log everything, then register the finished run).
    version = register(run_id, info.get("model_id", "unknown"))
    return run_id, version


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Log a Phase 10 training run to MLflow.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("run_name", nargs="?", help="a run under ../data/llm-training/runs/")
    group.add_argument(
        "--register-existing", metavar="RUN_ID", help="register an already-logged run again"
    )
    args = parser.parse_args(argv)

    if args.register_existing:
        configure()  # `register` itself only needs the tracking URI set, not an open run
        model_id = mlflow.get_run(args.register_existing).data.params.get("model_id", "unknown")
        version = register(args.register_existing, model_id)
        run_id = args.register_existing
    else:
        info, adapter_dir = load_run(args.run_name)
        run_id, version = publish(args.run_name, info, adapter_dir)

    print(f"Logged run -> {run_id}")
    print(f"Registered {MODEL_NAME} v{version}, alias {PRODUCTION_ALIAS!r}")
    # The run's own experiment, not a hardcoded 0: tracking.py logs to
    # 'llm-extraction-fallback', so a fixed /experiments/0/ link opened the wrong page.
    experiment_id = mlflow.get_run(run_id).info.experiment_id
    print(f"{mlflow.get_tracking_uri()}/#/experiments/{experiment_id}/runs/{run_id}")


if __name__ == "__main__":
    main()
