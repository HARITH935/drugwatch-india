"""The monthly pipeline: CDSCO's new alerts, all the way to the gold layer.

One run does what Phases 1-4 built, in order:

    download the portal's NSQ and spurious tabs + any new alert PDFs
        -> verify raw/ against its recorded hashes
        -> extract PDF rows and portal rows into bronze
        -> clean bronze into silver with PySpark
        -> validate silver with Great Expectations
        -> load silver into Postgres
        -> dbt build (every model, then its 44 tests)

Each task is the command CLAUDE.md §10 documents, so any failure can be reproduced by hand from
the log (ADR 0012). What makes this safe to run on a schedule is that **every step is
idempotent**, and each for a different reason worth knowing:

- **downloads**: a month already stored is skipped without even a request; with `--refresh` it is
  re-fetched but stored only if the bytes differ. So re-running costs nothing and cannot duplicate.
- **bronze**: one Parquet file per source document, rewritten in place.
- **silver**: `build_silver` writes `mode("overwrite")`, so silver is replaced wholesale, never
  appended to. This is the step that would otherwise double the archive on every run.
- **Postgres**: the loader is `TRUNCATE` + `COPY` in one transaction (ADR 0011).
- **gold**: dbt rebuilds its tables.

**Why `--refresh` on the last two months.** The portal downloader's own comment says it: state
labs report late, so a month's JSON keeps changing after that month ends. Fetching the current
interval's month *and* the one before it is what picks those late rows up - and because unchanged
bytes are never re-stored, asking twice is free.

**Schedule: the 10th of each month, 03:00.** Not the 1st: CDSCO publishes a month's alerts during
the following month, so a run on the 1st would mostly fetch a month nobody has published yet. The
run that fires on 10 November covers the interval starting 10 October, so
`data_interval_start` names October - the alert month to ask for.

`max_active_runs=1` because every task writes shared state: two runs at once would have two Spark
jobs overwriting the same silver prefix.

Still to come: failure emails (step 4), a run log (step 5), the backfill DAG (step 2), and the
watchlist alerts that Phase 9's backend will expose.
"""

from datetime import datetime, timedelta

from airflow import DAG

from drugwatch_orchestration.notifications import failure_email
from drugwatch_orchestration.pipeline import processing_chain
from drugwatch_orchestration.tasks import uv_task

# Airflow renders these; `data_interval_start` is a pendulum datetime, so it can do the arithmetic.
THIS_MONTH = "{{ data_interval_start.strftime('%Y-%m') }}"
LAST_MONTH = "{{ data_interval_start.subtract(months=1).strftime('%Y-%m') }}"

with DAG(
    dag_id="monthly_pipeline",
    description="CDSCO's monthly alerts: download -> bronze -> silver -> validate -> gold",
    start_date=datetime(2026, 11, 1),
    schedule="0 3 10 * *",  # 03:00 on the 10th: after CDSCO publishes the previous month
    catchup=False,  # historical reprocessing is the backfill DAG's job (step 2), not this one's
    max_active_runs=1,  # every task writes shared state: silver, Postgres, gold
    tags=["drugwatch", "pipeline"],
    # Every task in this DAG emails on FINAL failure (retries exhausted), and says nothing when
    # the backoff recovers on its own. Set here rather than in the task factory so a DAG cannot
    # quietly be written without it.
    default_args={"on_failure_callback": failure_email},
    doc_md=__doc__,
) as dag:
    # --- 1. download -------------------------------------------------------------------------
    # Two tabs, two tasks: they are independent requests and a failure in one should not hide
    # the other. Both ask for this month and last month, with --refresh, for late-reported rows.
    download_nsq = uv_task(
        task_id="download_portal_nsq",
        project="ingestion",
        module="drugwatch_ingestion.sources.cdsco_portal",
        arguments=f"--tab nsq --refresh --month {THIS_MONTH} --month {LAST_MONTH}",
    )
    download_spurious = uv_task(
        task_id="download_portal_spurious",
        project="ingestion",
        module="drugwatch_ingestion.sources.cdsco_portal",
        arguments=f"--tab spurious --refresh --month {THIS_MONTH} --month {LAST_MONTH}",
    )
    # `--all` is cheap for documents already stored: those are skipped with no request at all,
    # so this only really fetches the listing page plus anything genuinely new. Rate-limited to
    # one request every 3 s per host (CLAUDE.md §7), hence the longer timeout.
    download_pdfs = uv_task(
        task_id="download_cdsco_pdfs",
        project="ingestion",
        module="drugwatch_ingestion.sources.cdsco_pdf",
        arguments="--all",
        execution_timeout=timedelta(hours=2),
    )

    # --- 2-6. verify, extract, clean, validate, load, build gold ---------------------------
    # The same seven tasks the backfill DAG runs, built by one shared function so the two can
    # never drift apart (drugwatch_orchestration.pipeline).
    processing_starts, _ = processing_chain()

    # --- the shape of the run ----------------------------------------------------------------
    [download_nsq, download_spurious, download_pdfs] >> processing_starts
