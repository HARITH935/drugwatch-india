"""Airflow's configuration, assembled from this repo's own environment variables.

Airflow reads every setting from `AIRFLOW__<SECTION>__<KEY>` environment variables, which is why
there is no `airflow.cfg` in git: the file Airflow writes into AIRFLOW_HOME is generated, and
these variables override it. One source of truth, and the database password never lands in a file
(ADR 0012).

The values come from the same `.env` everything else in the repo uses, so Airflow connects to the
Postgres that `docker compose up` already started - database `airflow`, beside `staging` and
`gold`, never mixed in with them.
"""

import json
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

# SMTP defaults match docker-compose.yml's Mailpit, which accepts any credentials and no TLS.
# Production (Brevo) sets these in the environment: port 587 with SMTP_STARTTLS=true.
SMTP_DEFAULTS = {
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USERNAME": "drugwatch",
    "SMTP_PASSWORD": "any-value-works-with-mailpit",
    "SMTP_FROM": "alerts@drugwatch.local",
    "SMTP_STARTTLS": "false",
}


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


def smtp_connection(env: Mapping[str, str] = os.environ) -> str:
    """Airflow's `smtp_default` connection, as JSON, from the repo's own SMTP_* variables.

    Airflow normally keeps connections in its metadata database, entered through the UI. Building
    this one from the environment instead means local dev (Mailpit) and production (Brevo) differ
    only by `.env`, and Spring Boot's watchlist emails read the very same variables (CLAUDE.md §8)
    - one set of credentials, not two that can disagree.

    `disable_ssl` is always true because neither target speaks SMTPS on these ports; `disable_tls`
    is the inverse of SMTP_STARTTLS, so Mailpit gets a plain connection and Brevo gets STARTTLS.
    """
    settings = {name: env.get(name) or default for name, default in SMTP_DEFAULTS.items()}
    starttls = settings["SMTP_STARTTLS"].strip().lower() in {"1", "true", "yes", "on"}
    return json.dumps(
        {
            "conn_type": "smtp",
            "host": settings["SMTP_HOST"],
            "port": int(settings["SMTP_PORT"]),
            "login": settings["SMTP_USERNAME"],
            "password": settings["SMTP_PASSWORD"],
            "extra": {
                "from_email": settings["SMTP_FROM"],
                "disable_ssl": True,
                "disable_tls": not starttls,
                "timeout": 30,  # never let a hung mail server hold a task open
                "retry_limit": 3,
            },
        }
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
        # The SMTP connection failure emails use, built from .env rather than stored in the
        # metadata database. AIRFLOW_CONN_* is how Airflow reads a connection from the
        # environment, and it takes precedence over anything saved in the database.
        "AIRFLOW_CONN_SMTP_DEFAULT": smtp_connection(env),
    }
