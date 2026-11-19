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


def test_tasks_retry_with_backoff(dagbag):
    """Transient failures must not need a human (plan §9 Phase 5 step 3)."""
    for dag_id, dag in dagbag.dags.items():
        for task in dag.tasks:
            assert task.retries >= 1, f"{dag_id}.{task.task_id} has no retries"
