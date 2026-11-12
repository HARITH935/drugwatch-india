"""Phase 3 step 2, applied to the real bronze data: show what normalize_whitespace changes.

A read-only report (nothing is written back yet: dates, name-splitting and the other Phase 3
steps still need to run before a row is ready for silver/). It prints, per dataset, how many
values in each text column actually changed, and a few real before/after examples.

The column lists below name every "row content" field from the PDF and portal bronze schemas
(extraction/.../bronze.py's ROW_FIELDS, portal_bronze.py's FIELD_NAMES) - never a provenance
field (source_key, page, confidence, ...), which must stay exactly as recorded.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.clean_bronze
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from drugwatch_spark.clean_text import normalize_whitespace
from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
from drugwatch_spark.session import spark_session

# extraction/.../bronze.py ROW_FIELDS: every field a PDF family parser can produce.
PDF_TEXT_COLUMNS = [
    "serial_no", "product_name", "batch_no", "batch_details", "mfg_date", "expiry_date",
    "manufacturer", "failure_reason", "reported_by", "drawn_by", "drawn_from", "firm_reply",
    "remarks", "sample_source", "status", "regulatory_action", "report_year", "sales_outlets",
    "manufacturer_response",
]  # fmt: skip
# portal_bronze.py FIELD_NAMES.values(): every portal field renamed into the bronze schema.
PORTAL_TEXT_COLUMNS = [
    "generic_name", "product_name", "brand_name", "batch_no", "mfg_date", "expiry_date",
    "manufacturer", "failure_reason", "reporting_source", "reported_by", "reporting_month",
    "remarks", "firm_reply", "spurious_manufacturer_name", "spurious_manufactured_by",
]  # fmt: skip
BEFORE_SUFFIX = "__before"  # a copy of each column, kept so after-cleaning can be compared to it


def report(df: DataFrame, columns: list[str], name: str) -> None:
    print(f"\n{name}: {df.count()} rows")
    # Keep an untouched copy of each column first, so "before" and "after" sit in the SAME row of
    # the SAME DataFrame: no join, no risk of two separately-computed row orderings drifting apart.
    with_copies = df
    for column in columns:
        with_copies = with_copies.withColumn(column + BEFORE_SUFFIX, F.col(column))
    cleaned = normalize_whitespace(with_copies, columns)

    for column in columns:
        before, after = F.col(column + BEFORE_SUFFIX), F.col(column)
        diffs = cleaned.where(before != after).select(before.alias("before"), after.alias("after"))
        count = diffs.count()
        if count == 0:
            continue
        print(f"  {column}: {count} value(s) changed")
        for row in diffs.limit(2).collect():
            print(f"    before: {row['before']!r}")
            print(f"    after:  {row['after']!r}")


def main() -> None:
    spark = spark_session("clean-bronze")
    try:
        report(read_bronze(spark, PDF), PDF_TEXT_COLUMNS, "PDF bronze")
        report(read_bronze(spark, PORTAL), PORTAL_TEXT_COLUMNS, "Portal bronze")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
