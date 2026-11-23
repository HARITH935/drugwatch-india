"""Phase 10 step 4's lightweight half: log a finished training run to MLflow.

No model is loaded here - this only reads a run directory (`adapter/` + `run_info.json`,
written by `train.py` on the Mac or downloaded from the Colab notebook) and talks to MLflow. That
split is deliberate: `train.py` needs the memory a model plus gradients plus an optimizer's state
takes and competes with Docker's resident VM for the same 8 GB (ADR 0019's amendments); this script
needs neither, so it is the one that is allowed to need Docker up.

Run (from llm/, Docker up, after a run exists in ../data/llm-training/runs/<name>/ - unzip a
Colab download there first if that's where it trained):
    uv run --env-file ../.env python -m drugwatch_llm.publish_run <run_name>
"""

import argparse
import json
from pathlib import Path

import mlflow

from drugwatch_llm.tracking import start_run

RUN_DIR = Path("../data/llm-training/runs")


def load_run(run_name: str) -> tuple[dict, Path]:
    run_dir = RUN_DIR / run_name
    info_path = run_dir / "run_info.json"
    adapter_dir = run_dir / "adapter"
    if not info_path.exists():
        raise FileNotFoundError(f"{info_path} not found - did training actually finish?")
    if not adapter_dir.exists():
        raise FileNotFoundError(f"{adapter_dir} not found - the adapter wasn't saved there")
    return json.loads(info_path.read_text()), adapter_dir


def publish(run_name: str, info: dict, adapter_dir: Path) -> str:
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
        return run.info.run_id


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Log a Phase 10 training run to MLflow.")
    parser.add_argument("run_name")
    args = parser.parse_args(argv)

    info, adapter_dir = load_run(args.run_name)
    run_id = publish(args.run_name, info, adapter_dir)

    print(f"Logged run {args.run_name!r} -> {run_id}")
    print(f"{mlflow.get_tracking_uri()}/#/experiments/0/runs/{run_id}")


if __name__ == "__main__":
    main()
