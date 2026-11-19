"""Run Airflow's own CLI with this project's configuration already applied.

    uv run --env-file ../.env python -m drugwatch_orchestration.cli standalone
    uv run --env-file ../.env python -m drugwatch_orchestration.cli dags list

Why a wrapper instead of plain `airflow ...`: Airflow needs a dozen environment variables to
point at the right database, DAG folder and port, and the one that matters most - the database
URL - contains a password. Building them in one place (config.airflow_env) means every command,
and every DAG parsed by every component, sees exactly the same settings, and the password is
assembled in memory from `.env` rather than written into airflow.cfg (ADR 0012).
"""

import os
import sys

from drugwatch_orchestration.config import AIRFLOW_HOME, airflow_env


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv

    # setdefault, not assignment: a variable already exported in the shell wins, which is what
    # makes "run one command against a different database" possible without editing code.
    for name, value in airflow_env().items():
        os.environ.setdefault(name, value)
    AIRFLOW_HOME.mkdir(parents=True, exist_ok=True)

    from airflow.__main__ import main as airflow_main

    sys.argv = ["airflow", *arguments]
    airflow_main()


if __name__ == "__main__":
    main()
