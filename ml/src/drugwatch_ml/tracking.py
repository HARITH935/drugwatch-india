"""MLflow setup: where runs go, and what every run has to record to be reproducible.

A tracked run that cannot be reproduced is a number in a table. So `start_run` refuses to open one
without three tags:

- **the git commit**, so the code is recoverable;
- **whether the working tree was dirty**, because a commit hash is a lie if it was;
- **a fingerprint of the feature table** - its row count, its column names and the newest cutoff
  in it - so a run can be told apart from the same code on rebuilt data.

The tracking server runs in Docker (ADR 0016) and proxies artifacts, so nothing here holds S3
credentials: artifacts go to the server over HTTP and the server writes them to RustFS.
"""

import os
import subprocess
from pathlib import Path

# The agent-hint suppression lives in drugwatch_ml/__init__.py, which runs before this import.
import mlflow
import pandas as pd

EXPERIMENT = "manufacturer-risk"
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
        # A commit hash describes the code only if nothing was edited on top of it. Recording the
        # difference is the whole point: a dirty run is a result nobody can reproduce exactly.
        "git_dirty": str(dirty).lower(),
    }


def data_fingerprint(frame: pd.DataFrame, cutoff_column: str = "as_of_month") -> dict[str, str]:
    """Enough to tell this feature table apart from a rebuilt one.

    Not a hash of the values: the mart is rebuilt monthly and a hash would change every time
    without saying what changed. Row count, column set and the newest cutoff do say.
    """
    newest = str(frame[cutoff_column].max()) if cutoff_column in frame.columns else "unknown"
    return {
        "data_rows": str(len(frame)),
        "data_columns": str(len(frame.columns)),
        "data_newest_cutoff": newest,
    }


def configure(experiment: str = EXPERIMENT) -> str:
    """Point MLflow at the server and make sure the experiment exists. Returns its id."""
    mlflow.set_tracking_uri(tracking_uri())
    return mlflow.set_experiment(experiment).experiment_id


def start_run(name: str, frame: pd.DataFrame | None = None, **tags: str):
    """Open a run with the reproducibility tags already attached.

    Returns MLflow's run context manager, so callers use it as `with start_run(...) as run:`.
    """
    configure()
    all_tags = {**code_version(), **tags}
    if frame is not None:
        all_tags |= data_fingerprint(frame)
    return mlflow.start_run(run_name=name, tags=all_tags)
