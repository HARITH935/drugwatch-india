"""The email a human gets when the pipeline finally gives up on a task.

**Only final failure.** Airflow fires `on_failure_callback` when a task instance reaches `failed`;
an attempt that will be retried reaches `up_for_retry` instead, and fires nothing. So this sends
one email per task that failed *after* its retries were exhausted - and none at all for the
transient failures the backoff recovers from. The backfill run on 2026-11-19 is the case in point:
both downloads failed three times and recovered by themselves (0 emails), while the two extraction
tasks ran out of retries (2 emails). Every email therefore means something a person must act on,
which is the only way alerting survives contact with an inbox.

The message is built by a pure function (`failure_message`) and sent by the callback, so the
content can be tested without an SMTP server - the part that usually goes untested and then
arrives malformed at 3am.

Credentials come from the same `.env` as everything else, assembled into Airflow's SMTP
connection by `config.airflow_env()` (ADR 0012): Mailpit locally, Brevo in production
(CLAUDE.md §8).
"""

import os
from typing import Any

# The address that gets the alerts. Mailpit catches everything locally, so the default is only a
# label; in production this is a real inbox set through the environment.
ALERT_TO = os.environ.get("ALERT_EMAIL_TO") or "alerts@drugwatch.local"


def failure_message(context: dict[str, Any]) -> tuple[str, str]:
    """(subject, html) for a task that has finally failed.

    What goes in, and why each piece: the DAG and task say *what* broke; the try count says the
    retries were really used up rather than the task failing once; the dates say which run; the
    exception is the first thing a person wants; and the reproduction command is what turns the
    email into a fix, because every task here is a documented command (ADR 0012) that can be
    pasted into a terminal.
    """
    instance = context.get("task_instance")
    dag_run = context.get("dag_run")
    exception = context.get("exception")

    dag_id = getattr(instance, "dag_id", "unknown-dag")
    task_id = getattr(instance, "task_id", "unknown-task")
    try_number = getattr(instance, "try_number", "?")
    max_tries = getattr(instance, "max_tries", "?")
    run_id = getattr(dag_run, "run_id", "unknown-run")
    started = getattr(instance, "start_date", None)
    log_url = getattr(instance, "log_url", None)
    # The rendered command, when the operator has one: this is what makes the email actionable.
    command = getattr(getattr(instance, "task", None), "bash_command", None)

    subject = f"[DrugWatch] {dag_id}.{task_id} failed after {try_number} tries"

    rows = [
        ("DAG", dag_id),
        ("Task", task_id),
        ("Run", run_id),
        ("Attempts", f"{try_number} of {int(max_tries) + 1}" if max_tries != "?" else try_number),
        ("Started", started.isoformat() if started else "unknown"),
        ("Error", str(exception) if exception else "no exception recorded"),
    ]
    table = "".join(
        f"<tr><td style='padding:2px 10px 2px 0'><b>{name}</b></td><td>{value}</td></tr>"
        for name, value in rows
    )
    html = [
        "<p>A DrugWatch pipeline task has failed and used up its retries.</p>",
        f"<table>{table}</table>",
    ]
    if command:
        html.append(
            f"<p>Reproduce it by hand (every task is a documented command):</p><pre>{command}</pre>"
        )
    if log_url:
        html.append(f"<p><a href='{log_url}'>Full task log</a></p>")
    html.append(
        "<p style='color:#666;font-size:90%'>Sent because the task reached <code>failed</code>, "
        "not <code>up_for_retry</code>: the transient failures the backoff recovers from are "
        "deliberately silent.</p>"
    )
    return subject, "".join(html)


def failure_email(context: dict[str, Any]) -> None:
    """`on_failure_callback`: build the message and send it over SMTP.

    Imported lazily so that parsing a DAG - which happens constantly, including in CI where no
    SMTP provider connection exists - never needs the hook.
    """
    from airflow.providers.smtp.hooks.smtp import SmtpHook

    subject, html = failure_message(context)
    with SmtpHook() as hook:
        hook.send_email_smtp(to=ALERT_TO, subject=subject, html_content=html)
