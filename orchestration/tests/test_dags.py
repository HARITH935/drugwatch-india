"""DAG integrity tests: every DAG file must import, parse and be acyclic.

This is the test that catches the mistakes Airflow is famous for - a typo in a DAG file, a cycle
between tasks, two tasks with the same id, a missing import - without a database, a scheduler or
a running task. It is the cheapest possible safety net and it runs in CI, where `dbt build` and
the pipeline itself cannot (they need Postgres and real data).
"""

import os

import pytest


@pytest.fixture(scope="module")
def dagbag(tmp_path_factory):
    """Every DAG in dags/, parsed. SQLite in a temp dir: parsing touches no real database."""
    home = tmp_path_factory.mktemp("airflow_home")
    os.environ["AIRFLOW_HOME"] = str(home)
    os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = f"sqlite:///{home}/airflow.db"
    os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"

    from airflow.models import DagBag

    from drugwatch_orchestration.config import DAGS_FOLDER

    # Airflow 3.4's DagBag takes no `include_examples`: example loading is a config setting,
    # which the environment above switches off.
    return DagBag(dag_folder=str(DAGS_FOLDER))


def test_every_dag_file_parses(dagbag):
    assert not dagbag.import_errors, f"DAG files failed to import: {dagbag.import_errors}"


def test_there_is_at_least_one_dag(dagbag):
    assert dagbag.dags, "no DAGs found - is the dags folder path right?"


def test_no_dag_has_a_cycle(dagbag):
    for dag_id, dag in dagbag.dags.items():
        dag.validate()  # raises on cycles and on invalid task relationships
        assert dag.tasks, f"{dag_id} has no tasks"


def test_every_dag_is_owned_and_documented(dagbag):
    """A DAG nobody can explain is a DAG nobody can fix at 2am."""
    for dag_id, dag in dagbag.dags.items():
        assert dag.description, f"{dag_id} has no description"
        assert dag.doc_md, f"{dag_id} has no doc_md"


# Tasks that validate parameters rather than do work. A bad month range is wrong on the first
# millisecond and still wrong on the last, so retrying it only delays the error by 15 minutes -
# which is exactly what happened before `check_month_range` was given a task of its own.
VALIDATION_ONLY_TASKS = {"check_month_range"}


def test_work_tasks_retry_and_validation_tasks_do_not(dagbag):
    """Transient failures must not need a human (plan §9 Phase 5 step 3) - but permanent ones
    must not be retried at all."""
    for dag_id, dag in dagbag.dags.items():
        for task in dag.tasks:
            where = f"{dag_id}.{task.task_id}"
            if task.task_id in VALIDATION_ONLY_TASKS:
                assert task.retries == 0, f"{where} validates parameters: it must fail fast"
            else:
                assert task.retries >= 1, f"{where} has no retries"


def test_work_tasks_have_a_timeout(dagbag):
    """A task that hangs must fail and alert, not block the DAG for ever."""
    for dag_id, dag in dagbag.dags.items():
        for task in dag.tasks:
            if task.task_id not in VALIDATION_ONLY_TASKS:
                assert task.execution_timeout, f"{dag_id}.{task.task_id} has no execution_timeout"
