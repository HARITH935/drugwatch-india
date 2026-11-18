"""Phase 4 step 1: load the silver table from RustFS into the Postgres staging schema.

Why not Spark (ADR 0011): silver is ~7,100 rows. `docs/benchmarks.md` measured Spark at ~2
minutes and 2.7 GB of peak memory for exactly this data, against ~6 s and 181 MB for a single
process. This reads silver with the same pyarrow reader the Great Expectations gate uses, and
pushes the rows with `COPY`, Postgres' bulk-load path.

The load is a **full refresh inside one transaction**: TRUNCATE and COPY commit together.

- Re-running it is therefore safe and leaves the same table (Phase 5 requires idempotent tasks).
- No reader ever sees an empty or half-loaded table: until the transaction commits, every other
  session still sees the previous load. A TRUNCATE committed on its own would leave the website
  querying an empty table for as long as the load takes.
- Anything that goes wrong - a type that will not convert, a row count that does not match -
  rolls the whole thing back, so a failed load never half-replaces good data.

Incremental loading (only the new month) is deliberately not done: at this size a full refresh
costs under a second, and it cannot drift from silver the way an incremental load can.

Run (from warehouse/, with Postgres and RustFS up):
    uv run --env-file ../.env python -m drugwatch_warehouse.load_silver
    uv run --env-file ../.env python -m drugwatch_warehouse.load_silver --dry-run
"""

import os
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pandas as pd
import psycopg

from drugwatch_quality.silver import read_silver
from drugwatch_warehouse import schema

# Defaults match docker-compose.yml and .env.example. Host 5433 because the container's 5432 is
# published on 5433 to avoid clashing with another project's Postgres (CLAUDE.md Section 10).
DEFAULTS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5433",
    "POSTGRES_USER": "drugwatch",
    "POSTGRES_DB": "drugwatch",
}
INTEGER_TYPES = ("integer", "bigint", "smallint")


def connection_info(env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Connection settings from the environment. The password is never defaulted."""
    password = env.get("POSTGRES_PASSWORD")
    if not password:
        raise KeyError("set POSTGRES_PASSWORD (see .env.example)")
    settings = {name: env.get(name) or default for name, default in DEFAULTS.items()}
    return {
        "host": settings["POSTGRES_HOST"],
        "port": int(settings["POSTGRES_PORT"]),
        "user": settings["POSTGRES_USER"],
        "dbname": settings["POSTGRES_DB"],
        "password": password,
    }


def to_postgres_value(value: Any, pg_type: str) -> Any:
    """One pandas value as something psycopg can send.

    Three conversions, each for a real reason seen in silver:

    - **numpy -> Python** (`.tolist()`): pandas hands out numpy scalars (`int32`, `bool_`) and
      numpy arrays for the list columns. Converting here keeps the driver out of guessing.
    - **missing -> None**: pandas spells "missing" as NaN, NaT or pd.NA depending on the column;
      Postgres spells it NULL. Checked after the array conversion, because `pd.isna` on a list
      returns a list of answers, not one answer.
    - **float -> int** for integer columns: `page` is float64 in pandas purely because 97% of
      rows are NULL (portal rows have no page), and a float64 column cannot hold NA otherwise.
      Sending 160.0 to an `integer` column would fail; `int()` is exact here because every real
      value is a whole page number.
    """
    if hasattr(value, "tolist"):  # numpy scalar or array
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [None if item is None else str(item) for item in value]
    if value is None:
        return None
    if pd.isna(value):  # NaN, NaT and pd.NA all land here
        return None
    if pg_type in INTEGER_TYPES and isinstance(value, float):
        return int(value)
    return value


def check_columns(frame: pd.DataFrame) -> None:
    """Refuse to load a frame whose columns are not exactly the ones staging expects.

    A silver schema change should stop the pipeline, not quietly load 31 of 32 columns or write
    a new column into nothing."""
    expected, actual = set(schema.COLUMNS), set(frame.columns)
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    if missing or extra:
        raise ValueError(
            f"silver does not match {schema.QUALIFIED}: "
            f"missing {missing or 'nothing'}, unexpected {extra or 'nothing'}"
        )


def rows_for_copy(frame: pd.DataFrame) -> Iterator[Sequence[Any]]:
    """Every row as a tuple in COPY's column order, converted for Postgres.

    A generator, not a list: COPY streams, so the whole converted table never exists at once."""
    ordered = frame[list(schema.COLUMNS)]
    types = list(schema.COLUMNS.values())
    for row in ordered.itertuples(index=False, name=None):
        yield tuple(
            to_postgres_value(value, pg_type) for value, pg_type in zip(row, types, strict=True)
        )


def load(frame: pd.DataFrame, connection: psycopg.Connection) -> int:
    """Replace the staging table's contents with `frame`, in one transaction. Returns the count.

    The caller owns the transaction (psycopg commits when its `connect()` block exits), so a
    raise anywhere in here rolls back the TRUNCATE as well as the COPY."""
    check_columns(frame)
    if frame.empty:
        raise ValueError("refusing to load: silver is empty (this would wipe the staging table)")

    with connection.cursor() as cursor:
        cursor.execute(schema.create_schema_sql())
        cursor.execute(schema.create_table_sql())
        cursor.execute(f"TRUNCATE {schema.QUALIFIED}")
        with cursor.copy(schema.copy_sql()) as copy:
            for row in rows_for_copy(frame):
                copy.write_row(row)
        # noqa S608: no user input anywhere near this - the table name is a module constant.
        cursor.execute(f"SELECT count(*) FROM {schema.QUALIFIED}")  # noqa: S608
        loaded = cursor.fetchone()[0]

    # Counted inside the same transaction: if COPY lost rows, nothing is committed.
    if loaded != len(frame):
        raise RuntimeError(f"loaded {loaded} rows but silver has {len(frame)}; rolling back")
    return loaded


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Load silver into the Postgres staging schema.")
    parser.add_argument("--dry-run", action="store_true", help="read and check; write nothing")
    args = parser.parse_args()

    frame = read_silver()
    print(f"silver: {len(frame)} rows, {len(frame.columns)} columns")
    check_columns(frame)
    print(f"columns match {schema.QUALIFIED} ({len(schema.COLUMNS)} columns)")
    if args.dry_run:
        print("--dry-run: nothing written")
        return

    info = connection_info()
    print(f"-> postgres {info['user']}@{info['host']}:{info['port']}/{info['dbname']}")
    with psycopg.connect(**info) as connection:
        loaded = load(frame, connection)
    print(f"loaded {loaded} rows into {schema.QUALIFIED}\n")

    with psycopg.connect(**info) as connection, connection.cursor() as cursor:
        cursor.execute(f"""
            SELECT source_dataset,
                   count(*)                                  AS rows,
                   count(*) FILTER (WHERE is_spurious)       AS spurious,
                   count(DISTINCT manufacturer_canonical)    AS manufacturers,
                   min(alert_month) || ' .. ' || max(alert_month) AS months
            FROM {schema.QUALIFIED}
            GROUP BY source_dataset ORDER BY rows DESC
        """)  # noqa: S608 - no user input: the table name is a module constant
        print(f"{'source_dataset':16} {'rows':>6} {'spurious':>9} {'makers':>7}  months")
        for dataset, rows, spurious, makers, months in cursor.fetchall():
            print(f"{dataset:16} {rows:6} {spurious:9} {makers:7}  {months}")


if __name__ == "__main__":
    main()
