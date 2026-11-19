"""The part of the pipeline that both DAGs share, and the month arithmetic the backfill needs.

The monthly DAG and the backfill DAG differ only in what they fetch: one asks for the month that
just ended, the other for a range a person chose. Everything after the download - verify, extract,
clean, validate, load, build gold - is identical, so it is built once here.

That is not just tidiness. If the two DAGs each carried their own copy of those seven tasks, a fix
to one (a new validation step, a changed timeout) would silently not apply to the other, and the
backfill would quietly stop matching the monthly run it is supposed to reproduce.

No TaskGroup: a group would prefix every task id (`process.build_silver`), which would orphan the
run history the monthly DAG already has. Flat ids, one shared builder.
"""

import re
from datetime import timedelta

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import BaseOperator  # Airflow 3's public type; airflow.models.* is deprecated

from drugwatch_orchestration.run_log import record_run
from drugwatch_orchestration.tasks import dbt_task, uv_task

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# The CDSCO portal's JSON begins in January 2019 (ADR 0004). Older alerts exist only as PDFs,
# which are fetched by document id, not by month, so a month range cannot reach them.
PORTAL_FIRST_MONTH = "2019-01"
MAX_MONTHS = 120  # ten years: a guard against a typo asking CDSCO for a thousand months


def months_in_range(start_month: str, end_month: str) -> list[str]:
    """Every month from `start_month` to `end_month` inclusive, as 'YYYY-MM' strings.

    Raises on anything that is not a sane range, because the alternative is a backfill that
    silently fetches nothing (or everything). The message says what to do instead.
    """
    for name, value in (("start_month", start_month), ("end_month", end_month)):
        if not MONTH_PATTERN.match(str(value)):
            raise ValueError(f"{name} must look like 2019-01, got {value!r}")
    if end_month < start_month:
        raise ValueError(f"end_month {end_month} is before start_month {start_month}")
    if start_month < PORTAL_FIRST_MONTH:
        raise ValueError(
            f"the CDSCO portal starts at {PORTAL_FIRST_MONTH} (ADR 0004); "
            f"months before that exist only as PDFs, which are fetched by document id. "
            f"Got start_month={start_month}"
        )

    start_year, start_index = (int(part) for part in start_month.split("-"))
    end_year, end_index = (int(part) for part in end_month.split("-"))
    count = (end_year - start_year) * 12 + (end_index - start_index) + 1
    if count > MAX_MONTHS:
        raise ValueError(f"{count} months is more than the {MAX_MONTHS}-month limit")

    months = []
    year, index = start_year, start_index
    for _ in range(count):
        months.append(f"{year:04d}-{index:02d}")
        year, index = (year + 1, 1) if index == 12 else (year, index + 1)
    return months


def month_arguments(start_month: str, end_month: str) -> str:
    """`--month 2019-01 --month 2019-02 ...` for the downloader's repeatable flag.

    Used as a Jinja macro inside a DAG, so a bad range fails while the task's command is being
    rendered - before any request is made - with the ValueError above in the log.
    """
    return " ".join(f"--month {month}" for month in months_in_range(start_month, end_month))


def check_month_range(params: dict) -> list[str]:
    """Validate the backfill's parameters and say what it will do. Runs with NO retries.

    Found by testing a deliberately bad range: the ValueError below is raised while a task's
    command is rendered, and Airflow treats that like any other task failure - so it was retried
    with exponential backoff, taking 15 minutes to report a typo that is wrong on the first
    millisecond and will be wrong on the last.

    A parameter error is permanent, not transient. So the range is checked once, in a task of its
    own with `retries=0`, before anything downstream can run. Transient failures (a CDSCO
    timeout, RustFS restarting) still get their retries where they belong - on the tasks that do
    the work.
    """
    months = months_in_range(params["start_month"], params["end_month"])
    refresh = bool(params["refresh_downloads"])
    print(f"{len(months)} months: {months[0]} .. {months[-1]}")
    print(
        "re-asking CDSCO for each of them (--refresh)"
        if refresh
        else "NOT asking CDSCO for anything already stored; rebuilding from raw/"
    )
    return months


def processing_chain() -> tuple[BaseOperator, BaseOperator]:
    """The seven tasks that turn raw/ into gold, wired up. Returns (first, last).

    Must be called inside a `with DAG(...)` block; the operators attach themselves to it.
    """
    # raw/ is the source of truth and is never modified (CLAUDE.md §5). If a stored file no longer
    # matches its recorded SHA-256, every step after this would process the wrong bytes - so this
    # runs before extraction, not after.
    verify_raw = uv_task(
        task_id="verify_raw_archive",
        project="ingestion",
        module="drugwatch_ingestion.inventory",
    )

    # Different sources, different output prefixes, so these two run in parallel.
    extract_pdfs = uv_task(
        task_id="extract_pdf_bronze",
        project="extraction",
        module="drugwatch_extraction.bronze",
        arguments="--all",
    )
    extract_portal = uv_task(
        task_id="extract_portal_bronze",
        project="extraction",
        module="drugwatch_extraction.portal_bronze",
        arguments="--all",
    )

    # The heaviest task: a JVM, ~2.7 GB peak, 152.9 s measured. It rebuilds the WHOLE silver table
    # (`mode("overwrite")`), which is why a backfill of two months and a backfill of five years
    # cost the same from here on - and why neither can leave silver half-updated.
    build_silver = uv_task(
        task_id="build_silver",
        project="spark",
        module="drugwatch_spark.build_silver",
        execution_timeout=timedelta(hours=1),
    )

    # Before the load, never after: bad data must not reach the warehouse the website reads.
    # One retry only - a failing expectation is a data problem, and retrying repeats it.
    validate_silver = uv_task(
        task_id="validate_silver",
        project="quality",
        module="drugwatch_quality.suite",
        retries=1,
    )

    load_silver = uv_task(
        task_id="load_silver_to_postgres",
        project="warehouse",
        module="drugwatch_warehouse.load_silver",
    )
    build_gold = dbt_task(task_id="dbt_build", command="build")

    # The run log (step 5). `trigger_rule="all_done"` is the whole point: it runs whatever
    # happened upstream, because a run log that only records successes cannot answer "which
    # checks failed" - which is half of what the step asks for. It is a PythonOperator rather
    # than a command because it reads from Postgres, RustFS and dbt's artifact and writes one
    # row; there is no CLI for that, and inventing one to keep the pattern pure would be worse.
    summarise = PythonOperator(
        task_id="record_run_log",
        python_callable=record_run,
        trigger_rule="all_done",
        retries=1,
        execution_timeout=timedelta(minutes=10),
    )

    verify_raw >> [extract_pdfs, extract_portal] >> build_silver
    build_silver >> validate_silver >> load_silver >> build_gold >> summarise
    return verify_raw, summarise
