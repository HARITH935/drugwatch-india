"""Reprocess a historical range: the same pipeline, on months you choose.

Two different jobs need this, and the parameters are what tell them apart:

1. **A parser or cleaning fix.** Phase 2's extraction or Phase 3's cleaning changes, and every
   row in the archive has to be rebuilt from `raw/` with the new rules. Run it with
   `refresh_downloads = false`: not one request reaches CDSCO, and the months only decide what is
   re-fetched, which in this case is nothing - everything is rebuilt from the bytes already
   stored. **This is the common case.**
2. **A gap in `raw/`.** A month was never fetched, or CDSCO has revised one since. Run it with
   `refresh_downloads = true` and the months to re-ask for.

The `raw/` layer is never modified either way (CLAUDE.md §5): a refresh stores a NEW snapshot
beside the old one when the bytes differ, and nothing at all when they do not. Reprocessing reads
raw/ and rewrites bronze, silver and gold - the derived layers - which is exactly the direction
the medallion pattern expects a fix to flow.

**There is no partial rebuild, and that is deliberate.** `build_silver` reads all of bronze and
writes silver with `mode("overwrite")`, so a backfill of two months and one of five years do the
same work after the download step (~4 minutes). Rebuilding one month in place would mean
partition-level overwrites, a silver table that is a mix of two code versions, and manufacturer
clustering computed over a subset - which would produce different canonical names than the full
archive does. Slower and whole is the correct trade here.

**Parameters** (set them in the UI's "Trigger DAG w/ config", or with `--conf`):

- `start_month`, `end_month` - 'YYYY-MM', inclusive. Validated while the command is rendered, so
  a typo fails before any request: the portal begins at 2019-01 (ADR 0004), the range cannot run
  backwards, and 120 months is the limit.
- `refresh_downloads` - false (default) reprocesses from raw/ without asking CDSCO for anything
  already stored; true re-fetches the range.

No schedule: this DAG only ever runs because a person triggered it.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.models.param import Param
from airflow.providers.standard.operators.python import PythonOperator

from drugwatch_orchestration.notifications import failure_email
from drugwatch_orchestration.pipeline import check_month_range, month_arguments, processing_chain
from drugwatch_orchestration.tasks import uv_task

# Rendered by Jinja, so a bad range raises in the task's own log, with the reason, before the
# command exists. `month_arguments` is exposed to the template as a macro below.
MONTHS = "{{ month_arguments(params.start_month, params.end_month) }}"
# Without --refresh the downloader skips any month already stored without making a request at
# all, so the download tasks cost nothing in the reprocess-only case.
REFRESH = "{{ '--refresh' if params.refresh_downloads else '' }}"

with DAG(
    dag_id="backfill_pipeline",
    description="Reprocess a chosen month range: raw/ -> bronze -> silver -> validate -> gold",
    start_date=datetime(2026, 11, 1),
    schedule=None,  # triggered by a person, with parameters; never on a timer
    catchup=False,
    max_active_runs=1,  # shares silver, Postgres and gold with the monthly DAG
    tags=["drugwatch", "pipeline", "backfill"],
    # Every task in this DAG emails on FINAL failure (retries exhausted), and says nothing when
    # the backoff recovers on its own. Set here rather than in the task factory so a DAG cannot
    # quietly be written without it.
    default_args={"on_failure_callback": failure_email},
    params={
        "start_month": Param(
            "2019-01",
            type="string",
            pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
            title="First month to re-fetch (YYYY-MM)",
            description="The CDSCO portal's JSON starts at 2019-01 (ADR 0004).",
        ),
        "end_month": Param(
            "2026-09",
            type="string",
            pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
            title="Last month to re-fetch (YYYY-MM), inclusive",
        ),
        "refresh_downloads": Param(
            False,
            type="boolean",
            title="Re-ask CDSCO for those months?",
            description=(
                "Leave off to rebuild from the bytes already in raw/ - the usual case after a "
                "parser or cleaning fix. Turn on only to fill a gap or pick up a revision."
            ),
        ),
    },
    # Makes month_arguments() callable inside any templated field in this DAG.
    user_defined_macros={"month_arguments": month_arguments},
    doc_md=__doc__,
) as dag:
    # Checked first, in one second, with no retries: a bad month range is a permanent error and
    # must not be retried for 15 minutes before anyone hears about it. The only PythonOperator in
    # these DAGs - everything that does real work is a documented command (ADR 0012), but
    # validating parameters is not work, it is a gate.
    check_range = PythonOperator(
        task_id="check_month_range",
        python_callable=check_month_range,
        # No op_kwargs: Airflow passes context keys whose names match the callable's parameters,
        # so `params` arrives as the real dict. Passing `op_kwargs={"params": "{{ params }}"}`
        # instead renders Jinja to a *string*, and the task then failed with
        # "TypeError: string indices must be integers" rather than the explanation it exists to
        # print. The tests were green and the task did fail fast - just for the wrong reason.
        # Only reading the actual message showed it.
        retries=0,
    )

    # The PDF downloader is deliberately absent: it fetches by document id, not by month, and a
    # reprocess has no reason to re-list CDSCO's website (CLAUDE.md §7 - rate-limit and do not
    # ask for what you already have). New documents are the monthly DAG's job.
    download_nsq = uv_task(
        task_id="download_portal_nsq_range",
        project="ingestion",
        module="drugwatch_ingestion.sources.cdsco_portal",
        arguments=f"--tab nsq {REFRESH} {MONTHS}",
        execution_timeout=timedelta(hours=3),  # 120 months at >=3 s per request, plus retries
    )
    download_spurious = uv_task(
        task_id="download_portal_spurious_range",
        project="ingestion",
        module="drugwatch_ingestion.sources.cdsco_portal",
        arguments=f"--tab spurious {REFRESH} {MONTHS}",
        execution_timeout=timedelta(hours=3),
    )

    processing_starts, _ = processing_chain()
    check_range >> [download_nsq, download_spurious] >> processing_starts
