"""The run log: what each pipeline run processed, and what it changed.

Plan §9 Phase 5 step 5 asks for "files processed, rows added, checks passed/failed". The hard part
is not the table - it is where the numbers come from.

**Every number here is read from a structured source, never scraped from a task's stdout.** Step 1
left that as the open question, and parsing logs would have been the fragile answer: a reworded
print statement would silently turn a run log into fiction. Instead:

- **files in raw/** - counted from RustFS itself, through the same `RawStore` the downloaders use.
- **rows** - counted in Postgres (`staging.silver_nsq`, `gold.fact_nsq_sample`), which is the
  warehouse's own answer rather than a task's claim about it.
- **dbt** - read from `dbt/target/run_results.json`, the artifact dbt writes for exactly this
  purpose, with its `generated_at` checked against this run's start so a stale file from an
  earlier run can never be reported as this one's.
- **task states** - recorded by each task as it finishes (`record_task`, wired as a callback),
  not inferred afterwards. Airflow 3 runs tasks in a subprocess that talks to the API server, so
  reaching into Airflow's own database from inside a task is exactly the kind of coupling that
  breaks on upgrade.
- **"added"** - the difference against the previous recorded run, which is why the counts are
  stored rather than the deltas: a delta cannot be recomputed later, a count can.

Idempotency, as everywhere else in Phase 5: both tables are keyed on (dag_id, run_id) and written
with `ON CONFLICT ... DO UPDATE`, so re-running a run corrects its row instead of adding a second.
"""

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from drugwatch_orchestration.config import POSTGRES_DEFAULTS, REPO_ROOT

SCHEMA = "ops"  # operational bookkeeping: never read by the website or the model
RUN_TABLE = f"{SCHEMA}.pipeline_run"
TASK_TABLE = f"{SCHEMA}.pipeline_task"
DBT_RUN_RESULTS = REPO_ROOT / "dbt" / "target" / "run_results.json"
# dbt statuses that mean "fine": a model that built, a test that passed, a node skipped on purpose.
DBT_GOOD = {"success", "pass", "skipped"}

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {RUN_TABLE} (
    dag_id              text        NOT NULL,
    run_id              text        NOT NULL,
    logical_date        timestamptz,
    started_at          timestamptz,
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    duration_seconds    numeric,
    status              text,                 -- success / failed, from the tasks' own states
    tasks_succeeded     int,
    tasks_failed        int,
    quality_check       text,                 -- the Great Expectations task's state
    raw_files           int,                  -- files processed: everything in raw/
    raw_files_added     int,                  -- vs the previous recorded run
    silver_rows         int,
    silver_rows_added   int,
    gold_fact_rows      int,
    dbt_nodes_total     int,
    dbt_nodes_passed    int,
    dbt_nodes_failed    int,
    PRIMARY KEY (dag_id, run_id)
);

CREATE TABLE IF NOT EXISTS {TASK_TABLE} (
    dag_id              text        NOT NULL,
    run_id              text        NOT NULL,
    task_id             text        NOT NULL,
    state               text,
    try_number          int,
    started_at          timestamptz,
    finished_at         timestamptz,
    duration_seconds    numeric,
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dag_id, run_id, task_id)
);
"""


def postgres_connection(env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Connection settings for the drugwatch database - the warehouse's, not Airflow's.

    Reuses the same defaults as the metadata connection (docker-compose's published port), and
    the same rule: the password is read, never defaulted.
    """
    password = env.get("POSTGRES_PASSWORD")
    if not password:
        raise KeyError("set POSTGRES_PASSWORD (see .env.example)")
    settings = {name: env.get(name) or default for name, default in POSTGRES_DEFAULTS.items()}
    return {
        "host": settings["POSTGRES_HOST"],
        "port": int(settings["POSTGRES_PORT"]),
        "user": settings["POSTGRES_USER"],
        "dbname": env.get("POSTGRES_DB") or "drugwatch",
        "password": password,
        "connect_timeout": 10,
    }


def dbt_node_counts(path: Path = DBT_RUN_RESULTS, not_before: datetime | None = None):
    """(total, passed, failed) from dbt's own run_results.json, or None if it cannot be trusted.

    `not_before` is this run's start. dbt rewrites the file on every invocation, so a file older
    than the run belongs to a previous one - reporting it as this run's result would be a lie that
    looks like data. Missing file, unreadable JSON and stale file all return None, and the run log
    stores nulls, which is the honest answer to "we do not know".
    """
    try:
        document = json.loads(path.read_text())
        results = document["results"]
        generated = document["metadata"]["generated_at"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None
    if not_before is not None:
        stamp = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        if stamp < not_before:
            return None
    passed = sum(1 for result in results if result.get("status") in DBT_GOOD)
    return len(results), passed, len(results) - passed


def table_count(cursor, table: str) -> int | None:
    """Row count, or None when the table does not exist yet (a first run, or a failed load)."""
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    if not cursor.fetchone()[0]:
        return None
    cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - table names are constants here
    return cursor.fetchone()[0]


def added_since(current: int | None, previous: int | None) -> int | None:
    """How much a count grew. None when either side is unknown - never a misleading zero."""
    if current is None or previous is None:
        return None
    return current - previous


def state_name(state: Any) -> str:
    """'success', not 'TaskInstanceState.SUCCESS'.

    Airflow hands the callback a `TaskInstanceState` enum, and `str()` on it gives the enum's
    repr. Stored that way, the summary's lookup for 'success' matched nothing and recorded a
    perfect run as failed - a run log that lies is worse than no run log. Found by reading the
    row, not by the tests, which never saw a real enum.
    """
    return str(getattr(state, "value", state) or "unknown")


def record_task(context: dict[str, Any]) -> None:
    """Task callback: write this task's own outcome. Wired for both success and failure.

    Each task recording itself is what makes the per-task log possible without querying Airflow's
    metadata database from inside a task.
    """
    instance = context.get("task_instance")
    if instance is None:
        return
    started = getattr(instance, "start_date", None)
    finished = getattr(instance, "end_date", None) or datetime.now(
        tz=started.tzinfo if started else None
    )
    duration = (finished - started).total_seconds() if started and finished else None
    row = (
        getattr(instance, "dag_id", "unknown"),
        getattr(context.get("dag_run"), "run_id", "unknown"),
        getattr(instance, "task_id", "unknown"),
        state_name(getattr(instance, "state", None)),
        getattr(instance, "try_number", None),
        started,
        finished,
        duration,
    )
    with psycopg.connect(**postgres_connection()) as connection, connection.cursor() as cursor:
        cursor.execute(DDL)
        cursor.execute(
            f"""INSERT INTO {TASK_TABLE}
                    (dag_id, run_id, task_id, state, try_number, started_at, finished_at,
                     duration_seconds)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dag_id, run_id, task_id) DO UPDATE SET
                    state = excluded.state,
                    try_number = excluded.try_number,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    duration_seconds = excluded.duration_seconds,
                    recorded_at = now()""",  # noqa: S608 - table name is a module constant
            row,
        )


def record_run(**context: Any) -> dict[str, Any]:
    """The final task: count what this run processed and changed, and store one row for it.

    Runs with `trigger_rule="all_done"`, so a failed run is logged too - a run log that only
    records successes cannot answer "which checks failed", which is half of what step 5 asks for.
    """
    dag_run = context.get("dag_run")
    instance = context.get("task_instance")
    dag_id = getattr(instance, "dag_id", "unknown")
    run_id = getattr(dag_run, "run_id", "unknown")
    started = getattr(dag_run, "start_date", None)
    logical_date = getattr(dag_run, "logical_date", None)

    files = raw_file_count()
    dbt_counts = dbt_node_counts(not_before=started)

    with psycopg.connect(**postgres_connection()) as connection, connection.cursor() as cursor:
        cursor.execute(DDL)
        silver_rows = table_count(cursor, "staging.silver_nsq")
        gold_rows = table_count(cursor, "gold.fact_nsq_sample")

        # The states this run's tasks recorded for themselves, excluding this one (still running).
        cursor.execute(
            f"""SELECT state, count(*) FROM {TASK_TABLE}
                WHERE dag_id = %s AND run_id = %s AND task_id <> %s GROUP BY state""",  # noqa: S608
            (dag_id, run_id, getattr(instance, "task_id", "")),
        )
        states = dict(cursor.fetchall())
        succeeded = states.get("success", 0)
        failed = sum(
            count for state, count in states.items() if state not in {"success", "skipped"}
        )

        cursor.execute(
            f"""SELECT state FROM {TASK_TABLE}
                WHERE dag_id = %s AND run_id = %s AND task_id = 'validate_silver'""",  # noqa: S608
            (dag_id, run_id),
        )
        quality = (cursor.fetchone() or [None])[0]

        # The previous recorded run of ANY dag: the deltas are about the data, not about one DAG.
        cursor.execute(
            f"""SELECT raw_files, silver_rows FROM {RUN_TABLE}
                WHERE NOT (dag_id = %s AND run_id = %s)
                ORDER BY recorded_at DESC LIMIT 1""",  # noqa: S608
            (dag_id, run_id),
        )
        previous = cursor.fetchone() or (None, None)

        finished = datetime.now(tz=started.tzinfo if started else None)
        summary = {
            "dag_id": dag_id,
            "run_id": run_id,
            "logical_date": logical_date,
            "started_at": started,
            "duration_seconds": (finished - started).total_seconds() if started else None,
            "status": "failed" if failed else "success",
            "tasks_succeeded": succeeded,
            "tasks_failed": failed,
            "quality_check": quality,
            "raw_files": files,
            "raw_files_added": added_since(files, previous[0]),
            "silver_rows": silver_rows,
            "silver_rows_added": added_since(silver_rows, previous[1]),
            "gold_fact_rows": gold_rows,
            "dbt_nodes_total": dbt_counts[0] if dbt_counts else None,
            "dbt_nodes_passed": dbt_counts[1] if dbt_counts else None,
            "dbt_nodes_failed": dbt_counts[2] if dbt_counts else None,
        }
        columns = ", ".join(summary)
        placeholders = ", ".join(f"%({name})s" for name in summary)
        updates = ", ".join(
            f"{name} = excluded.{name}" for name in summary if name not in {"dag_id", "run_id"}
        )
        cursor.execute(
            f"""INSERT INTO {RUN_TABLE} ({columns}) VALUES ({placeholders})
                ON CONFLICT (dag_id, run_id) DO UPDATE SET {updates}, recorded_at = now()""",  # noqa: S608
            summary,
        )

    def delta(value: int | None) -> str:
        return "" if value is None else f" ({value:+d})"

    print(
        f"{dag_id} {run_id}: {summary['status']} - "
        f"{summary['tasks_succeeded']} tasks ok, {summary['tasks_failed']} failed"
    )
    print(f"  raw/   {files} files{delta(summary['raw_files_added'])}")
    print(f"  silver {silver_rows} rows{delta(summary['silver_rows_added'])}")
    print(f"  gold   {gold_rows} fact rows")
    print(f"  dbt    {summary['dbt_nodes_passed']}/{summary['dbt_nodes_total']} nodes passed")
    print(f"  checks validate_silver = {quality}")
    return summary


def raw_file_count() -> int | None:
    """Every object in the raw bucket, counted through the downloaders' own S3 client.

    Returns None rather than raising if RustFS cannot be reached: a run log that fails to write
    because one of its figures is unavailable loses the whole record of the run.
    """
    try:
        from drugwatch_ingestion.store import META_SUFFIX, RawStore

        store = RawStore.from_env()
        paginator = store.s3.get_paginator("list_objects_v2")
        # Counting SIDECARS, not files. The sidecar is written second and is the store's own
        # "this file is complete" marker (store.py), so this counts complete items and ignores a
        # half-written one. Counting non-.json keys instead was wrong in the other direction and
        # was caught by comparing with `inventory`: the portal's raw snapshots ARE .json, so that
        # filter hid 118 of 331 files.
        return sum(
            1
            for page in paginator.paginate(Bucket=store.bucket)
            for item in page.get("Contents", [])
            if item["Key"].endswith(META_SUFFIX)
        )
    except Exception as error:  # noqa: BLE001 - never let bookkeeping break the run log
        print(f"could not count raw/ objects: {type(error).__name__}: {error}")
        return None
