"""Read the gold layer into pandas, for exploration.

Why a module and not SQL typed into notebook cells: a notebook is committed with its outputs
cleared (ADR 0013), so anything that lives only in a cell is unreviewable and untestable. The
queries that matter live here, where they can be imported, tested and reused by the next notebook.

**Every connection is opened read-only.** psycopg's `read_only` puts the session in a read-only
transaction, so the database itself refuses an INSERT, UPDATE or DROP from here - not a convention
but an error. Exploration happens on a warehouse that took four minutes and a Spark job to build;
a stray `DELETE` typed into the wrong cell at midnight should be impossible, not merely unlikely.

Gold only (CLAUDE.md §5). Superset, the ML pipeline and the API read gold, so the exploration that
decides what the dashboards show must read the same tables, or it will quietly invent a second
definition of every figure.
"""

import os
from collections.abc import Mapping
from typing import Any

import pandas as pd
import psycopg

# Same defaults as the warehouse loader and the orchestrator: docker-compose's published port.
DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5433",
    "POSTGRES_USER": "drugwatch",
    "POSTGRES_DB": "drugwatch",
}
GOLD_SCHEMA = "gold"


def connection_info(env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Connection settings from the environment. The password is never defaulted."""
    password = env.get("POSTGRES_PASSWORD")
    if not password:
        raise KeyError("set POSTGRES_PASSWORD (see .env.example)")
    settings = {name: env.get(name) or default for name, default in DEFAULTS.items()}
    return {
        "host": settings["POSTGRES_HOST"],
        "port": int(settings["POSTGRES_PORT"]),
        "user": settings["POSTGRES_USER"],
        "dbname": settings["POSTGRES_DB"],
        "password": password,
        "connect_timeout": 10,
    }


def query(sql: str, params: tuple[Any, ...] | None = None) -> pd.DataFrame:
    """Run one SELECT and return it as a DataFrame, in a read-only transaction.

    Column names come from the cursor's description rather than being written out by hand, so a
    renamed column shows up as a renamed column instead of silently landing under the wrong name.
    """
    with psycopg.connect(**connection_info()) as connection:
        connection.read_only = True  # the database refuses any write from this session
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [column.name for column in cursor.description or []]
            return pd.DataFrame(cursor.fetchall(), columns=columns)


def gold_tables() -> pd.DataFrame:
    """What the gold layer holds right now, with each table's row count.

    Row counts come from `count(*)` per table rather than from the planner's estimate in
    `pg_class.reltuples`: the estimate is only as fresh as the last ANALYZE, and a figure that is
    silently stale is worse than one that takes a second longer.
    """
    names = query(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (GOLD_SCHEMA,),
    )
    counts = [
        query(f"SELECT count(*) AS rows FROM {GOLD_SCHEMA}.{name}").iloc[0]["rows"]  # noqa: S608
        for name in names["table_name"]
    ]
    return names.assign(rows=counts)


def data_freshness() -> pd.DataFrame:
    """When the warehouse was last loaded, and by which pipeline run.

    Read from `ops.pipeline_run` (Phase 5 step 5) rather than from a timestamp inside gold: the
    run log is the only place that knows whether the last run actually succeeded.
    """
    return query(
        """
        SELECT dag_id, run_id, status, recorded_at, raw_files, silver_rows, gold_fact_rows,
               dbt_nodes_passed, dbt_nodes_total, quality_check
        FROM ops.pipeline_run
        ORDER BY recorded_at DESC
        LIMIT 5
        """
    )
