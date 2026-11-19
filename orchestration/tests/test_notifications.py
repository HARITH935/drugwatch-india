"""What the failure email says, tested without an SMTP server.

The content is the part that usually goes untested and then arrives at 3am missing the one fact a
person needed. `failure_message` is a pure function precisely so it can be checked here.
"""

import datetime as dt
from types import SimpleNamespace

from drugwatch_orchestration.notifications import failure_message


def context(**overrides):
    """An Airflow callback context, close enough for the message builder."""
    task = SimpleNamespace(
        bash_command="uv run --env-file ../.env python -m drugwatch_spark.build_silver"
    )
    instance = SimpleNamespace(
        dag_id="monthly_pipeline",
        task_id="build_silver",
        try_number=4,
        max_tries=3,
        start_date=dt.datetime(2026, 11, 19, 3, 0, tzinfo=dt.UTC),
        log_url="http://localhost:8082/log?task_id=build_silver",
        task=task,
    )
    base = {
        "task_instance": instance,
        "dag_run": SimpleNamespace(run_id="scheduled__2026-11-10T03:00:00+00:00"),
        "exception": RuntimeError(
            "Bash command failed. The command returned a non-zero exit code 1."
        ),
    }
    base.update(overrides)
    return base


def test_the_subject_names_the_dag_the_task_and_the_attempts():
    subject, _ = failure_message(context())
    assert "monthly_pipeline.build_silver" in subject
    assert "4 tries" in subject
    assert subject.startswith("[DrugWatch]")  # so an inbox rule can file it


def test_the_body_carries_the_error_and_the_run():
    _, html = failure_message(context())
    assert "non-zero exit code 1" in html
    assert "scheduled__2026-11-10T03:00:00+00:00" in html
    assert "4 of 4" in html  # try_number of max_tries + 1


def test_the_body_includes_the_command_to_reproduce_it():
    """The point of tasks being documented commands (ADR 0012): the email is actionable."""
    _, html = failure_message(context())
    assert "python -m drugwatch_spark.build_silver" in html


def test_the_body_links_to_the_log():
    _, html = failure_message(context())
    assert "http://localhost:8082/log?task_id=build_silver" in html


def test_it_explains_why_it_was_sent():
    """So nobody wonders whether every retry mails them. It does not."""
    _, html = failure_message(context())
    assert "up_for_retry" in html


def test_a_task_with_no_command_still_produces_a_message():
    """PythonOperator gates have no bash_command; the email must not crash on them."""
    instance = context()["task_instance"]
    instance.task = SimpleNamespace()  # no bash_command attribute
    subject, html = failure_message(context(task_instance=instance))
    assert subject and "Reproduce it by hand" not in html


def test_a_context_missing_everything_does_not_crash():
    """A callback that raises loses the alert entirely, so this must degrade, not explode."""
    subject, html = failure_message({})
    assert "unknown-dag" in subject and html
