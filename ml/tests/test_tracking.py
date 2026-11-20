"""What every tracked run must record to be reproducible."""

import pandas as pd
import pytest

from drugwatch_ml.tracking import code_version, data_fingerprint, tracking_uri


def test_the_tracking_uri_defaults_to_the_published_port():
    """5050, not 5000: macOS AirPlay Receiver listens on 5000 (docker-compose.yml)."""
    assert tracking_uri({}) == "http://localhost:5050"


def test_the_environment_wins():
    assert tracking_uri({"MLFLOW_TRACKING_URI": "http://mlflow:5000"}) == "http://mlflow:5000"


def test_every_run_records_whether_the_tree_was_dirty():
    """A commit hash describes the code only if nothing was edited on top of it. Without this tag
    a run looks reproducible when it is not."""
    version = code_version()
    assert version["git_dirty"] in ("true", "false")
    assert len(version["git_commit"]) == 40 or version["git_commit"] == "unknown"


def test_the_data_fingerprint_describes_the_table_not_its_bytes():
    """Deliberately not a hash: the mart is rebuilt monthly, and a hash would change every time
    without saying what changed. Row count, column count and newest cutoff do say."""
    frame = pd.DataFrame({"as_of_month": ["2025-01", "2025-02"], "x": [1, 2]})
    fingerprint = data_fingerprint(frame)
    assert fingerprint == {"data_rows": "2", "data_columns": "2", "data_newest_cutoff": "2025-02"}


def test_the_fingerprint_survives_a_frame_with_no_cutoff_column():
    """It must not crash the run it is only describing."""
    assert data_fingerprint(pd.DataFrame({"x": [1]}))["data_newest_cutoff"] == "unknown"


@pytest.mark.integration
def test_a_run_cannot_be_opened_without_the_reproducibility_tags(mlflow_available):
    from drugwatch_ml.tracking import start_run

    frame = pd.DataFrame({"as_of_month": ["2026-03"], "x": [1]})
    with start_run("test-tags", frame, purpose="unit test") as run:
        run_id = run.info.run_id
    import mlflow

    tags = mlflow.get_run(run_id).data.tags
    for required in ("git_commit", "git_dirty", "data_rows", "data_newest_cutoff"):
        assert required in tags, f"{required} missing from a run's tags"
    assert tags["purpose"] == "unit test"
