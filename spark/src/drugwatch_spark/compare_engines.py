r"""Phase 3 step 9: prove the pandas pipeline and the Spark pipeline produce the same silver.

The benchmark claims both engines run "the same cleaning job". That is only worth saying if the
outputs match, so this compares them row for row and column by column, and reports every
difference instead of a pass/fail.

It reads **the silver Spark actually wrote** (`s3a://silver/nsq/`) rather than starting Spark
again - that Parquet is the Spark pipeline's output - and runs the pandas pipeline beside it. So
this needs no JVM and takes seconds.

Values have to be normalised before comparing, because the two paths spell "missing" and "list"
differently even when they agree: Spark's nulls arrive as None/NaN/NaT depending on the column's
type, `page` comes back float64 (an int column with nulls cannot stay int), and list columns are
numpy arrays on one side and Python lists on the other.

Run (from spark/, RustFS up, after build_silver has written silver):
    uv run --env-file ../.env python -m drugwatch_spark.compare_engines
"""

import numpy as np
import pandas as pd

from drugwatch_spark.build_silver import SILVER_COLUMNS
from drugwatch_spark.pandas_pipeline import build_silver, read_bronze

SILVER_PATH = "silver/nsq"
PDF_PATH = "bronze/cdsco-pdf"
PORTAL_PATH = "bronze/cdsco-portal"
SORT_KEY = ["source_key", "page", "row_index"]  # unique across silver (proven in step 7)


def canonical(value):
    """One spelling for each value, so only real differences are left.

    Missing becomes None whatever its flavour; lists and numpy arrays become tuples; numbers
    become floats so int32 and float64 compare equal.
    """
    if isinstance(value, (list, tuple, np.ndarray)):
        return tuple(canonical(item) for item in value)
    # Every flavour of missing first, and NaN among them: NaN != NaN, so a NaN that survives
    # into the comparison makes a column look 100% different when both sides are simply empty.
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()  # a date read back as a midnight timestamp is the same date
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (np.integer, np.floating, int, float)) and not isinstance(value, bool):
        return float(value)  # int32 and float64 should compare equal
    return value


def normalised(frame: pd.DataFrame) -> dict[str, list]:
    """The frame sorted the same way on both sides, as plain lists of canonical values.

    Plain lists, not a DataFrame: handing the values back to pandas undoes the work, because it
    re-infers a float column and turns every canonical `None` straight back into NaN - and
    NaN != NaN makes an all-empty column look 100% different.
    """
    ordered = frame.sort_values(SORT_KEY, na_position="last").reset_index(drop=True)
    return {column: [canonical(value) for value in ordered[column]] for column in SILVER_COLUMNS}


def differences(spark_side: dict[str, list], pandas_side: dict[str, list]) -> dict[str, int]:
    """How many rows differ in each column (only the columns that differ at all)."""
    counts = {}
    for column in SILVER_COLUMNS:
        unequal = [
            index
            for index, (left, right) in enumerate(
                zip(spark_side[column], pandas_side[column], strict=True)
            )
            if left != right
        ]
        if unequal:
            counts[column] = len(unequal)
    return counts


def show_examples(spark_side, pandas_side, column: str, limit: int = 3) -> None:
    shown = 0
    for index, (left, right) in enumerate(
        zip(spark_side[column], pandas_side[column], strict=True)
    ):
        if left == right:
            continue
        key = spark_side["source_key"][index]
        print(f"    row {index} ({str(key)[-40:]})")
        print(f"      spark : {str(left)[:90]!r}")
        print(f"      pandas: {str(right)[:90]!r}")
        shown += 1
        if shown >= limit:
            return


def main() -> None:
    import sys
    import warnings

    warnings.filterwarnings("ignore")

    # Silver is partitioned, so its two partition columns come from the directory names.
    spark_written = read_bronze(SILVER_PATH, partitioning="hive")
    print(f"spark silver : {len(spark_written)} rows")
    produced = build_silver(read_bronze(PDF_PATH), read_bronze(PORTAL_PATH))
    print(f"pandas silver: {len(produced)} rows")

    missing = set(SILVER_COLUMNS) - set(produced.columns)
    extra = set(produced.columns) - set(SILVER_COLUMNS)
    if missing or extra:
        print(f"column mismatch - missing {sorted(missing)}, extra {sorted(extra)}")
        sys.exit(1)
    if len(spark_written) != len(produced):
        print("row counts differ, so a row-by-row comparison would be meaningless")
        sys.exit(1)

    left, right = normalised(spark_written), normalised(produced)
    counts = differences(left, right)
    if not counts:
        rows = len(left[SORT_KEY[0]])
        print(f"\nidentical: {rows} rows x {len(SILVER_COLUMNS)} columns agree exactly")
        sys.exit(0)

    total = sum(counts.values())
    print(f"\n{len(counts)} column(s) differ, {total} cell(s) in total:\n")
    for column, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"  {column}: {count} of {len(left[SORT_KEY[0]])} rows")
        show_examples(left, right, column)
    sys.exit(1)


if __name__ == "__main__":
    main()
