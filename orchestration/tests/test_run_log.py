"""The run log's reasoning: deltas, and whether dbt's artifact can be trusted for this run."""

import datetime as dt
import json

import pytest

from drugwatch_orchestration.run_log import added_since, dbt_node_counts, state_name


def write_results(path, generated_at: str, statuses: list[str]):
    path.write_text(
        json.dumps(
            {
                "metadata": {"generated_at": generated_at, "dbt_version": "1.12.7"},
                "results": [
                    {"status": status, "unique_id": f"model.x.{i}"}
                    for i, status in enumerate(statuses)
                ],
            }
        )
    )
    return path


# --- deltas ----------------------------------------------------------------------------------


def test_a_delta_is_the_difference():
    assert added_since(7126, 7000) == 126


def test_nothing_new_is_zero_not_null():
    assert added_since(7126, 7126) == 0


def test_a_shrinking_count_is_reported_as_negative():
    """Silver getting smaller is a real event (step 1 saw two duplicate findings collapse)."""
    assert added_since(7126, 7128) == -2


@pytest.mark.parametrize("current,previous", [(None, 10), (10, None), (None, None)])
def test_an_unknown_side_gives_no_delta(current, previous):
    """Never a misleading zero: 'we do not know' and 'nothing changed' are different answers."""
    assert added_since(current, previous) is None


# --- trusting dbt's artifact ------------------------------------------------------------------


def test_counts_models_and_tests_that_passed(tmp_path):
    path = write_results(
        tmp_path / "run_results.json",
        "2026-11-19T10:00:00Z",
        ["success", "pass", "pass", "skipped"],
    )
    assert dbt_node_counts(path) == (4, 4, 0)


def test_counts_failures(tmp_path):
    path = write_results(
        tmp_path / "run_results.json", "2026-11-19T10:00:00Z", ["success", "fail", "error"]
    )
    assert dbt_node_counts(path) == (3, 1, 2)


def test_a_file_older_than_this_run_is_refused(tmp_path):
    """dbt rewrites the artifact on every invocation, so a file from an earlier run must not be
    reported as this run's result - that would be a lie that looks like data."""
    path = write_results(tmp_path / "run_results.json", "2026-11-19T09:00:00Z", ["success"])
    run_started = dt.datetime(2026, 11, 19, 10, 0, tzinfo=dt.UTC)
    assert dbt_node_counts(path, not_before=run_started) is None


def test_a_file_from_this_run_is_accepted(tmp_path):
    path = write_results(tmp_path / "run_results.json", "2026-11-19T10:30:00Z", ["success", "pass"])
    run_started = dt.datetime(2026, 11, 19, 10, 0, tzinfo=dt.UTC)
    assert dbt_node_counts(path, not_before=run_started) == (2, 2, 0)


def test_a_missing_file_is_not_an_error(tmp_path):
    """A failed run may never reach dbt at all; the log stores nulls rather than crashing."""
    assert dbt_node_counts(tmp_path / "nothing.json") is None


def test_unreadable_json_is_not_an_error(tmp_path):
    path = tmp_path / "run_results.json"
    path.write_text("{ this is not json")
    assert dbt_node_counts(path) is None


# --- how a task's state is stored --------------------------------------------------------------


def test_an_airflow_state_enum_is_stored_by_its_value():
    """Airflow hands callbacks a TaskInstanceState enum. Stored as its repr
    ('TaskInstanceState.SUCCESS'), the summary's lookup for 'success' matched nothing and a
    perfect run was recorded as failed."""
    from airflow.utils.state import TaskInstanceState

    assert state_name(TaskInstanceState.SUCCESS) == "success"
    assert state_name(TaskInstanceState.FAILED) == "failed"


def test_a_plain_string_state_survives():
    assert state_name("success") == "success"


def test_a_missing_state_is_not_an_empty_string():
    assert state_name(None) == "unknown"
