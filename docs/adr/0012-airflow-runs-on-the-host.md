# ADR 0012 — Airflow runs on the host via uv, with its metadata in the existing Postgres

- **Status:** accepted
- **Date:** 2026-11-19
- **Phase:** 5 (Automation), step 1
- **Decided by:** Harith

## Context

Phase 5 orchestrates the whole pipeline with Airflow (plan §6). Every step it has to run already
exists as a command: `uv run --env-file ../.env python -m drugwatch_ingestion.cdsco_portal`,
`… drugwatch_spark.build_silver`, `… drugwatch_quality.suite`, `… drugwatch_warehouse.load_silver`,
`dbt build`. Those commands live in six separate uv projects, and the Spark one needs a JDK plus
the 686 MB Hadoop/AWS jar bundle (ADR 0008).

So the question is where Airflow itself runs, and the deciding factor is memory, measured rather
than assumed:

| | Measured |
|---|---|
| Docker VM allowance on this Mac | 5 GB |
| DrugWatch's four compose services | 245 MB |
| One Spark cleaning run | **2.7 GB peak** (`docs/benchmarks.md`) |
| Airflow 3's four components | ~1.5 GB |

Airflow *and* Spark inside the same 5 GB VM comes to ~4.5 GB. It fits on paper, and in Phase 3 it
already failed in practice: Spark runs crashed the Docker VM outright while another project's
container held 3.4 GB.

## Decision

1. Airflow runs **on the host**, as a new `orchestration/` uv project, like every other Python
   folder in this repo. Its tasks shell out to the same commands a person would type.
2. Its metadata database is a **new `airflow` database inside the Postgres container** that
   already runs, not a second Postgres and not SQLite.
3. Airflow is configured entirely through environment variables, assembled by
   `drugwatch_orchestration.config` and applied by the `drugwatch_orchestration.cli` wrapper, so
   there is one source of truth and **no password is written to a config file**.

## Why

- **The heavy job stays out of the VM.** Spark keeps the 2.7 GB it needs on the host, where it
  has the whole machine, instead of competing with Airflow inside a 5 GB cap.
- **Nothing about the existing commands changes.** No JDK in an image, no 686 MB jar baked into a
  layer, no ~2.5 GB image build over a slow link. A DAG task is the command from `CLAUDE.md` §10,
  which also makes the DAG readable: you can run any task by hand, exactly as written.
- **Secrets stay where they are.** Each task runs `uv run --env-file ../.env`, so credentials
  reach the task from `.env` and Airflow itself never stores or passes them.
- **SQLite was never an option.** Airflow's SQLite backend only supports the SequentialExecutor -
  one task at a time - which would make "retries, parallelism and backfill" untestable, and the
  project would have learned the wrong lesson about what Airflow does.
- **One Postgres, two databases.** Airflow's tables live in their own `airflow` database, so they
  cannot collide with `staging`/`gold`, and they survive `docker compose down` in the same named
  volume as everything else. A second Postgres container would buy isolation this project does
  not need, at a cost it cannot spare.

## Consequences

- **Airflow is not containerised in local dev**, which is a deviation from the "everything in
  compose" shape of Phase 0 and is the reason this ADR exists. Phase 12 decides how it is
  deployed; the DAGs themselves do not care, because they only shell out to commands.
- `AIRFLOW_HOME` is `orchestration/airflow_home/`, git-ignored: it holds logs, the generated
  `airflow.cfg` and the dev auth manager's password file.
- The DAGs run as **your user on this machine**, so they can see `~/.m2` (the prefetched jar),
  `~/.cache/uv`, and the JDK already installed. That is the convenience and also the limitation:
  the pipeline is reproducible on a machine prepared like this one, which Phase 12 must address.
- **`CLAUDE.md` §9 changes:** the layout put "Airflow DAGs" in `ingestion/`. They live in
  `orchestration/` instead, because every phase's project feeds the DAGs - ingestion, extraction,
  spark, quality, warehouse and dbt - and burying the orchestrator inside the first of them would
  make `ingestion/` depend on all the others.
- `docker compose down -v` deletes Airflow's run history along with the warehouse, since they
  share the volume. Acceptable: both are rebuildable from `raw/`.

## Alternatives rejected

| Option | Why not |
|---|---|
| Custom Airflow image in compose | Airflow + a 2.7 GB Spark job in a 5 GB VM that already died once; plus a JDK, the 686 MB jar and a ~2.5 GB image build |
| Airflow in compose, Spark triggered on the host | Needs the Docker socket mounted into a container (a real privilege-escalation path) or an SSH operator; a more complicated, less portable DAG |
| A second Postgres container for metadata | Production isolation for a 7,126-row warehouse, on an 8 GB laptop |
| SQLite metadata | SequentialExecutor only: no parallelism, explicitly not for real use |
