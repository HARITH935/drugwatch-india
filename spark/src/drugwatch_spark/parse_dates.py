"""Phase 3 step 3, portal dates: parse "Mon-YYYY" into real dates, and flag mfg_date >= expiry_date.

Scope, found by comparing real bronze data (2026-11-12): portal mfg_date/expiry_date are ALWAYS one
shape, "Mon-YYYY" (e.g. "Aug-2017") - zero exceptions in ~13,780 real values. PDF dates are not:
30-40 different shapes (MM/YYYY, DD-MM-YYYY, 2-digit years, letter-spaced, split across a line
break, Excel day numbers, textual rules like "5 Yrs from the date of Mfg." ...), several of which
overlap the letter-spacing problem clean_text.py already deferred. This module covers portal dates
only; PDF dates need their own careful, separately-evidenced pass.

parse_portal_dates() adds two columns:
- mfg_date_parsed, expiry_date_parsed (real DATE values; the original text columns are untouched,
  so the two can always be compared). No day is ever printed, so Spark takes the 1st of the month.
- dates_valid: True when mfg_date_parsed < expiry_date_parsed, False when it is not (found: 16 of
  6,876 rows where both dates parsed - a real CDSCO/portal data quality issue, not a parsing bug),
  None when either date is missing or didn't parse. This FLAGS a problem; it never drops or
  corrects a row (CLAUDE.md: never silently guess at what the data should have said).

try_to_date(), not to_date(): Spark 4's default (ANSI) mode makes to_date() raise and crash the
whole job on the first value it can't parse, rather than returning null for it - found while
checking this against real data, before it could happen during an actual pipeline run.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.parse_dates
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

PORTAL_DATE_FORMAT = "MMM-yyyy"  # Java/Spark pattern: abbreviated month name, 4-digit year


def parse_portal_dates(df: DataFrame) -> DataFrame:
    mfg = F.try_to_date(F.col("mfg_date"), PORTAL_DATE_FORMAT)
    expiry = F.try_to_date(F.col("expiry_date"), PORTAL_DATE_FORMAT)
    return (
        df.withColumn("mfg_date_parsed", mfg)
        .withColumn("expiry_date_parsed", expiry)
        .withColumn("dates_valid", F.col("mfg_date_parsed") < F.col("expiry_date_parsed"))
    )


def main() -> None:
    from drugwatch_spark.read_bronze import PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("parse-dates")
    try:
        df = parse_portal_dates(read_bronze(spark, PORTAL))
        total = df.count()
        mfg_ok = (
            df.where(F.col("mfg_date") != "").where(F.col("mfg_date_parsed").isNotNull()).count()
        )
        mfg_present = df.where(F.col("mfg_date") != "").count()
        print(f"{total} portal rows; mfg_date parsed: {mfg_ok} of {mfg_present} present values")

        # ~col, not "col == False": a nullable boolean column, and NOT(null) is null (excluded by
        # where()), so this keeps only rows definitely invalid - never the "couldn't tell" rows.
        invalid = df.where(~F.col("dates_valid"))
        print(f"rows where mfg_date >= expiry_date: {invalid.count()}")
        cols = ["alert_month", "mfg_date", "expiry_date"]
        for row in invalid.select(*cols).orderBy("alert_month").limit(10).collect():
            print(" ", row.asDict())
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
