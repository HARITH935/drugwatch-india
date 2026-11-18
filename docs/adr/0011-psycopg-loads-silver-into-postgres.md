# ADR 0011 — psycopg loads silver into Postgres, in its own `warehouse/` folder

- **Status:** accepted
- **Date:** 2026-11-18
- **Phase:** 4 (Warehouse), step 1
- **Decided by:** Harith

## Context

Phase 4 step 1 is "load silver data into Postgres staging schema". Silver is ~7,100 rows of
Parquet in RustFS; the gold layer dbt builds on top of it lives in Postgres. Something has to
carry the rows across, and the locked stack (§6) names no loader: Spark is listed for
*processing*, dbt for *transformation*, Postgres as the *warehouse*.

Two candidates were considered.

**Spark JDBC write.** Reuses PySpark, already in the stack, so no new Python library — but it
needs the PostgreSQL JDBC jar and pays the cost `docs/benchmarks.md` measured on exactly this
data: ~2 minutes of wall clock and ~2.7 GB of peak memory for 7,126 rows, nearly all of it JVM
start-up, against pandas' 6 s and 181 MB for the same work.

**pyarrow + psycopg.** `quality/` already reads silver with pyarrow for the same reason (ADR 0007,
and the Great Expectations suite runs in seconds with no JVM). psycopg is Postgres' current
Python driver and supports `COPY`, Postgres' bulk-load path.

## Decision

1. Silver is loaded by **pyarrow + psycopg 3**, using `COPY ... FROM STDIN`, not by Spark JDBC.
2. The loader lives in a **new top-level `warehouse/` folder** (a uv project, like every other
   Python folder), so `dbt/` stays a pure dbt project with no foreign tooling nested inside it.
   `CLAUDE.md` §9's repo layout gains the folder.
3. `warehouse/` depends on `drugwatch-quality` as an editable path dependency and imports its
   `read_silver()`, rather than copying the reader.

## Why

- **The benchmark is the argument.** Phase 3 step 9 measured Spark at ~19x the time and ~15x the
  memory of a single-process reader on this exact table. Having measured that, choosing Spark for
  a 7,000-row load would be ignoring our own evidence.
- **psycopg is barely an addition.** `dbt-postgres` (mandatory in §6) ships with a Postgres driver
  of its own, so Phase 4 was always going to put one in the repo. This makes it explicit and
  current (psycopg 3) rather than implicit and legacy (psycopg2).
- **`COPY`, not `INSERT`.** `COPY` is Postgres' bulk path: one stream instead of one statement per
  row. At 7,126 rows it is the difference between under a second and tens of seconds, and the gap
  grows linearly as CDSCO publishes each month.
- **One silver reader, not two.** The loader reading through `drugwatch_quality.silver` means the
  rows loaded into Postgres are read exactly the way the Great Expectations gate reads them. In
  Phase 5 the DAG runs *validate → load*; sharing the reader is what makes "what passed" and
  "what landed" provably the same rows. The cost is that `warehouse/`'s virtualenv contains Great
  Expectations, which it never calls — accepted over duplicating the reader and letting the two
  copies drift.

## Consequences

- `warehouse/` is a new CI matrix entry (lint, format, tests) and a new line in `CLAUDE.md` §9/§10.
- The load is a **full refresh in one transaction**: `TRUNCATE` + `COPY` together, so a re-run is
  idempotent (Phase 5 requires that) and no reader ever sees a half-loaded or empty table.
- Silver is small enough to hold in one process. If it ever is not, this decision is the one to
  revisit — Spark JDBC or a partition-at-a-time loader — and the trigger is memory, not row count.
- **Not an argument against Spark.** Phase 3 keeps PySpark for the reasons recorded in
  `docs/benchmarks.md` §"Why the project still uses PySpark". This ADR is about one load step.

## Alternatives rejected

| Option | Why not |
|---|---|
| Spark JDBC write | 2 minutes and 2.7 GB for 7,126 rows, measured, plus a JDBC jar to manage |
| `psycopg2` | In maintenance-only mode; psycopg 3 is the current release and has a better `COPY` API |
| SQLAlchemy / `pandas.to_sql` | Another dependency, and `to_sql` issues `INSERT`s — far slower than `COPY` |
| Loader inside `dbt/` | A uv project nested in a dbt project confuses both tools' conventions |
| Copy the silver reader into `warehouse/` | Two readers of one table drift apart silently |
