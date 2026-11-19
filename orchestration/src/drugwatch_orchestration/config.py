"""Airflow's configuration, assembled from this repo's own environment variables.

Airflow reads every setting from `AIRFLOW__<SECTION>__<KEY>` environment variables, which is why
there is no `airflow.cfg` in git: the file Airflow writes into AIRFLOW_HOME is generated, and
these variables override it. One source of truth, and the database password never lands in a file
(ADR 0012).

The values come from the same `.env` everything else in the repo uses, so Airflow connects to the
Postgres that `docker compose up` already started - database `airflow`, beside `staging` and
`gold`, never mixed in with them.
"""

import os
from collections.abc import Mapping
from pathlib import Path

# orchestration/src/drugwatch_orchestration/config.py -> the repo root is four levels up
REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION = REPO_ROOT / "orchestration"
AIRFLOW_HOME = ORCHESTRATION / "airflow_home"
DAGS_FOLDER = ORCHESTRATION / "dags"

# Postgres defaults match docker-compose.yml, as the warehouse loader's do
POSTGRES_DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5433",
    "POSTGRES_USER": "drugwatch",
}
METADATA_DATABASE = "airflow"  # Airflow's own tables; NOT the drugwatch database


def metadata_connection(env: Mapping[str, str] = os.environ) -> str:
    """The SQLAlchemy URL for Airflow's metadata database.

    The password is read, never defaulted: a missing one must fail here rather than let Airflow
    fall back to its SQLite default and silently start a second, empty history.
    """
    password = env.get("POSTGRES_PASSWORD")
    if not password:
        raise KeyError("set POSTGRES_PASSWORD (see .env.example)")
    settings = {name: env.get(name) or default for name, default in POSTGRES_DEFAULTS.items()}
    return (
        f"postgresql+psycopg2://{settings['POSTGRES_USER']}:{password}"
        f"@{settings['POSTGRES_HOST']}:{settings['POSTGRES_PORT']}/{METADATA_DATABASE}"
    )


def airflow_env(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Every AIRFLOW__* variable this project needs, as a dict to put into the environment."""
    return {
        "AIRFLOW_HOME": str(AIRFLOW_HOME),
        "AIRFLOW__CORE__DAGS_FOLDER": str(DAGS_FOLDER),
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": metadata_connection(env),
        # LocalExecutor: tasks run as subprocesses of the scheduler, in parallel, on this machine.
        # Enough for a monthly pipeline, and unlike SequentialExecutor it can actually demonstrate
        # retries and parallel branches (ADR 0012).
        "AIRFLOW__CORE__EXECUTOR": "LocalExecutor",
        # Airflow ships ~50 example DAGs. Loading them would bury two real ones and schedule
        # work nobody asked for.
        "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
        # A new DAG starts paused, so adding one never backfills by surprise the moment it parses.
        "AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION": "True",
        # Local dev only: skip the login screen. There is nothing to protect on 127.0.0.1, and a
        # generated password file is one more thing to lose. Phase 12 must not inherit this.
        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS": "True",
        # Bound to loopback for the same reason every compose port is (CLAUDE.md §10).
        "AIRFLOW__API__HOST": "127.0.0.1",
        "AIRFLOW__API__PORT": "8082",  # 8080/8081 are taken by Mailpit's neighbours and dbt docs
    }
