"""parse_dates.py: portal "Mon-YYYY" parsing and the mfg_date < expiry_date check."""

import datetime

from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.parse_dates import parse_portal_dates

SCHEMA = StructType(
    [StructField("mfg_date", StringType()), StructField("expiry_date", StringType())]
)


def parsed(spark, mfg, expiry):
    df = spark.createDataFrame([(mfg, expiry)], SCHEMA)
    return parse_portal_dates(df).collect()[0]


def test_a_real_portal_date_parses_to_the_first_of_the_month(spark):
    row = parsed(spark, "Aug-2017", "Jul-2022")

    assert row["mfg_date_parsed"] == datetime.date(2017, 8, 1)  # no day is ever printed
    assert row["expiry_date_parsed"] == datetime.date(2022, 7, 1)


def test_the_original_text_columns_are_untouched(spark):
    row = parsed(spark, "Aug-2017", "Jul-2022")

    assert (row["mfg_date"], row["expiry_date"]) == ("Aug-2017", "Jul-2022")


def test_a_normal_row_is_flagged_valid(spark):
    assert parsed(spark, "Aug-2017", "Jul-2022")["dates_valid"] is True


def test_mfg_on_or_after_expiry_is_flagged_invalid_not_silently_fixed(spark):
    # Real examples found in the portal data: the source says this, not a parsing mistake.
    assert parsed(spark, "Apr-2026", "Mar-2025")["dates_valid"] is False  # a year backwards
    assert parsed(spark, "Jun-2024", "Jun-2024")["dates_valid"] is False  # equal: not < expiry


def test_an_empty_or_garbage_date_becomes_null_not_a_crash(spark):
    for mfg in (None, "", "garbage", "45200", "Best before 36 months"):
        row = parsed(spark, mfg, "Jul-2022")
        assert row["mfg_date_parsed"] is None
        assert row["dates_valid"] is None  # can't say valid or invalid: one side is unknown


def test_month_name_case_does_not_matter(spark):
    assert parsed(spark, "aug-2017", "JUL-2022")["mfg_date_parsed"] == datetime.date(2017, 8, 1)


def test_a_doubled_dash_does_not_become_a_wildly_wrong_date(spark):
    # No real portal value has done this, but PDF dates (parse_pdf_dates.py, same "MMM-yyyy"
    # format) found that Java's lenient parser reads an extra "-" as a SIGN on the year and
    # "succeeds" with year -2026 (2027 BC) - a date so extreme even Python can't hold it. The same
    # shared safety net (plausible_year()) protects this module too.
    row = parsed(spark, "01/2024", "Aug--2017")

    assert row["expiry_date_parsed"] is None
    assert row["dates_valid"] is None
