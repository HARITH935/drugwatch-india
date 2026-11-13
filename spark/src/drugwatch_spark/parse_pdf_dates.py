"""Phase 3 step 3, PDF dates: parse the 5 formats proven safe, leave the messy rest for later.

PDF mfg_date/expiry_date have 30-40 different shapes (parse_dates.py's docstring has the full
picture). This covers only the formats checked, one at a time, against every real value, to prove
each is both common and UNAMBIGUOUS before adding it - never a guess:

    MM/yyyy      "10/2023"      MM/yy      "10/25"
    MMM-yy       "Apr-15"       MMM-yyyy   "Apr-2023"
    dd-MM-yyyy   "30-09-2025"   proven day-first: 17 real values have a first number over 12
                                (which can only be a day), and NONE have a second number over 12
                                (which would have proven month-first instead)

Together these 5 formats are MUTUALLY EXCLUSIVE on the real archive (checked: zero values match
more than one), and cover 88.8% / 88.6% of present mfg_date / expiry_date values.

Left for a separately-evidenced follow-up, on purpose: "DD.MM.YYYY" (period-separated: ordering not
yet checked), Excel day numbers ("45200"), textual expiry rules ("5 Yrs from the date of Mfg."),
letter-spaced and line-broken dates (clean_text.py's docstring explains why those need care), and
placeholders ("NM", "--", "Not Mentioned").

Same column names and dates_valid semantics as parse_dates.py (portal), so the two stay consistent
even though PDF and portal bronze are separate datasets in this phase.

Found while checking real results, not from any PDF value directly: `try_to_date("Apr--2026",
"MMM-yyyy")` does not fail on the doubled dash as expected - Java's parser reads the extra "-" as a
SIGN on the year field and "succeeds" with the year -2026 (2027 BC), a date so extreme that even
converting it to a Python date crashes. plausible_year() nulls out anything outside PLAUSIBLE_YEARS
(confidence.py's own range for this archive) before it ever reaches Python, so a future format or
value with the same quirk is caught here too, not just this one found case.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.parse_pdf_dates
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from drugwatch_spark.parse_dates import plausible_year

# Order doesn't affect the result (proven mutually exclusive above), but trying the most common
# shapes first means less wasted work on the overwhelming majority of rows.
FORMATS = ("MM/yyyy", "MMM-yy", "dd-MM-yyyy", "MM/yy", "MMM-yyyy")


def parse_pdf_dates(df: DataFrame) -> DataFrame:
    mfg = plausible_year(F.coalesce(*(F.try_to_date(F.col("mfg_date"), fmt) for fmt in FORMATS)))
    expiry = plausible_year(
        F.coalesce(*(F.try_to_date(F.col("expiry_date"), fmt) for fmt in FORMATS))
    )
    return (
        df.withColumn("mfg_date_parsed", mfg)
        .withColumn("expiry_date_parsed", expiry)
        .withColumn("dates_valid", F.col("mfg_date_parsed") < F.col("expiry_date_parsed"))
    )


def main() -> None:
    from drugwatch_spark.read_bronze import PDF, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("parse-pdf-dates")
    try:
        df = parse_pdf_dates(read_bronze(spark, PDF))
        for field in ("mfg_date", "expiry_date"):
            present = df.where(F.col(field).isNotNull() & (F.col(field) != "")).count()
            parsed_col = field.removesuffix("_date") + "_date_parsed"
            ok = df.where(
                F.col(field).isNotNull() & (F.col(field) != "") & F.col(parsed_col).isNotNull()
            ).count()
            print(f"{field}: {ok} of {present} present values parsed ({ok / present:.1%})")

        # ~col, not "col == False": dates_valid is nullable, and NOT(null) is null (excluded by
        # where()), so this keeps only rows definitely invalid, never the "couldn't tell" rows.
        invalid = df.where(~F.col("dates_valid"))
        print(f"\nrows where mfg_date >= expiry_date: {invalid.count()}")
        cols = ["family", "alert_month", "mfg_date", "expiry_date"]
        for row in invalid.select(*cols).orderBy("family", "alert_month").limit(10).collect():
            print(" ", row.asDict())
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
