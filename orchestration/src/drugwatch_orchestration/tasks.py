"""One way to turn a documented command into an Airflow task.

Every step of this pipeline already exists as a command in CLAUDE.md §10, in its own uv project.
A task is therefore not new logic - it is that command, run from that folder. Building them all
through one factory means the retry policy, the working directory and the `--env-file` handling
are decided once instead of copied into every DAG (ADR 0012).

Secrets: `uv run --env-file ../.env` makes the task read `.env` itself, so credentials go from
the file to the subprocess without Airflow storing, logging or templating them.
"""

from datetime import timedelta

from airflow.providers.standard.operators.bash import BashOperator

from drugwatch_orchestration.config import REPO_ROOT

# Retries with exponential backoff (plan §9 Phase 5 step 3). The failures worth retrying here are
# transient: a CDSCO page that times out, RustFS still starting, a Postgres connection refused.
# 15 minutes of backoff gives a restarting container time to come back; more than 3 attempts just
# delays the email about a real problem.
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = timedelta(minutes=2)
MAX_RETRY_DELAY = timedelta(minutes=15)


def uv_task(
    task_id: str,
    project: str,
    module: str,
    arguments: str = "",
    *,
    retries: int = DEFAULT_RETRIES,
    execution_timeout: timedelta | None = timedelta(hours=1),
    **kwargs,
) -> BashOperator:
    """A task that runs `python -m <module>` inside one of this repo's uv projects.

    `project` is the folder name (ingestion, extraction, spark, quality, warehouse). The command
    is exactly what CLAUDE.md §10 documents, so any failing task can be reproduced by hand by
    copying it out of the Airflow log.

    `execution_timeout` defaults to an hour: a task that hangs (a half-open HTTP connection, a
    Spark job waiting on a lock) must fail and alert rather than block the DAG for ever.
    """
    command = f"uv run --env-file ../.env python -m {module}"
    if arguments:
        command = f"{command} {arguments}"
    return BashOperator(
        task_id=task_id,
        bash_command=command,
        cwd=str(REPO_ROOT / project),  # so `../.env` resolves to the repo-root .env
        retries=retries,
        retry_delay=DEFAULT_RETRY_DELAY,
        retry_exponential_backoff=True,
        max_retry_delay=MAX_RETRY_DELAY,
        execution_timeout=execution_timeout,
        **kwargs,
    )


def dbt_task(task_id: str, command: str, **kwargs) -> BashOperator:
    """A task that runs a dbt command in `dbt/`.

    dbt finds the repo-root `.env` by itself (`load_dotenv(find_dotenv(usecwd=True))`), so this
    needs no --env-file - recorded in dbt/profiles.yml, and verified in Phase 4 step 2.
    """
    return BashOperator(
        task_id=task_id,
        bash_command=f"uv run dbt {command}",
        cwd=str(REPO_ROOT / "dbt"),
        retries=1,  # a failing dbt TEST is a data problem; retrying it just repeats the failure
        retry_delay=DEFAULT_RETRY_DELAY,
        execution_timeout=timedelta(minutes=30),
        **kwargs,
    )
