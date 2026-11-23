"""MLflow setup for Phase 10's runs. The same recipe as `ml/tracking.py` (code version tags, the
tracking server's address), not a shared import from it: that module is shaped around pandas
DataFrames and one experiment name for the risk model, which isn't a good fit for an LLM run whose
"data" is a training-set file, not a gold mart. Same conventions, separate project - the pattern
every uv project in this repo already follows for its own lint/test setup.

The tracking server runs in Docker (ADR 0016) and proxies artifacts, so nothing here holds S3
credentials: the adapter goes to the server over HTTP and the server writes it to RustFS.
"""

import os
import subprocess
from pathlib import Path

import mlflow

EXPERIMENT = "llm-extraction-fallback"
REPO = Path(__file__).resolve().parents[3]


def tracking_uri(env: dict[str, str] | None = None) -> str:
    """Where the tracking server is. Defaults to the published port in docker-compose.yml."""
    source = env if env is not None else dict(os.environ)
    return source.get("MLFLOW_TRACKING_URI", "http://localhost:5050")


def _git(*arguments: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *arguments],  # noqa: S607 - git resolved from PATH, as everywhere else here
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    return result.stdout.strip()


def code_version() -> dict[str, str]:
    """The commit this run was produced by, and whether the tree had uncommitted changes."""
    dirty = bool(_git("status", "--porcelain"))
    return {
        "git_commit": _git("rev-parse", "HEAD") or "unknown",
        "git_dirty": str(dirty).lower(),
    }


def configure(experiment: str = EXPERIMENT) -> str:
    """Point MLflow at the server and make sure the experiment exists. Returns its id."""
    mlflow.set_tracking_uri(tracking_uri())
    return mlflow.set_experiment(experiment).experiment_id


def start_run(name: str, **tags: str):
    """Open a run with the reproducibility tags already attached.

    Returns MLflow's run context manager, so callers use it as `with start_run(...) as run:`.
    """
    configure()
    return mlflow.start_run(run_name=name, tags={**code_version(), **tags})
