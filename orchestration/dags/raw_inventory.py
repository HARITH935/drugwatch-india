"""Check every file in raw/ against the SHA-256 recorded when it was downloaded.

The first DAG, and deliberately the smallest real one: a single task that verifies the archive
has not changed under us. It is here to prove the whole arrangement works end to end - Airflow on
the host, running a documented `uv run` command, reaching RustFS with credentials it never sees
itself (ADR 0012) - before the monthly pipeline is built on top of it.

It is also genuinely worth having. `raw/` is the project's source of truth and is never modified
(CLAUDE.md §5), so a mismatch between a file and its sidecar hash means something is wrong that
no later step would notice: every reprocessing run would quietly use the changed bytes.

`drugwatch_ingestion.inventory` exits non-zero on any problem, which is exactly what an Airflow
task needs - a non-zero exit is a failed task, and in step 4 that becomes an email.

Schedule: none for now. The monthly schedule belongs to the pipeline DAG (step 1 proper); this
one is triggered by hand, or by a person wondering whether the archive is still intact.
"""

from datetime import datetime

from airflow import DAG

from drugwatch_orchestration.tasks import uv_task

with DAG(
    dag_id="raw_inventory",
    description="Verify every raw/ file against its recorded SHA-256",
    # A fixed start date, not datetime.now(): a moving start date makes a DAG's run history
    # unreproducible and is the classic Airflow beginner trap.
    start_date=datetime(2026, 11, 1),
    schedule=None,  # triggered by hand; the monthly schedule lives on the pipeline DAG
    catchup=False,  # never backfill this: it checks the archive as it is now, not as it was
    tags=["drugwatch", "data-quality"],
    doc_md=__doc__,
) as dag:
    uv_task(
        task_id="verify_raw_checksums",
        project="ingestion",
        module="drugwatch_ingestion.inventory",
    )
