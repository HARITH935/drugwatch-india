"""parse_pdf_dates.py: the 5 proven-safe PDF date formats, grounded in real archive examples."""

import datetime

from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.parse_pdf_dates import parse_pdf_dates

SCHEMA = StructType(
    [StructField("mfg_date", StringType()), StructField("expiry_date", StringType())]
)


def parsed(spark, mfg, expiry):
    df = spark.createDataFrame([(mfg, expiry)], SCHEMA)
    return parse_pdf_dates(df).collect()[0]


def test_each_of_the_5_formats_parses_a_real_archive_example(spark):
    cases = [
        ("10/2023", datetime.date(2023, 10, 1)),  # MM/yyyy
        ("10/25", datetime.date(2025, 10, 1)),  # MM/yy
        ("Apr-15", datetime.date(2015, 4, 1)),  # MMM-yy
        ("Apr-2023", datetime.date(2023, 4, 1)),  # MMM-yyyy
        ("30-09-2025", datetime.date(2025, 9, 30)),  # dd-MM-yyyy (day 30 proves day-first)
    ]
    for text, expected in cases:
        assert parsed(spark, text, "01/2040")["mfg_date_parsed"] == expected


def test_a_doubled_dash_does_not_become_a_wildly_wrong_date(spark):
    # Real example: Java's lenient parser doesn't fail on "Apr--2026" as expected - it reads the
    # extra "-" as a SIGN on the year and "succeeds" with year -2026 (2027 BC), a date so extreme
    # that even converting it to a Python date crashes. plausible_year() must catch this.
    row = parsed(spark, "01/2024", "Apr--2026")

    assert row["expiry_date_parsed"] is None  # not a crash, not a wrong date: null
    assert row["dates_valid"] is None  # one side unknown: not flagged true OR false


def test_the_bisacodyl_row_that_proved_the_validity_check_is_needed(spark):
    # Real example: the PDF itself prints "Jun-42" as the manufacturing date (a CDSCO typo - the
    # expiry is 2026, 16 years earlier). Parsing takes the text at face value; the validity flag,
    # not the parser, is what is supposed to catch this - it must not be silently "corrected".
    row = parsed(spark, "Jun-42", "Apr-26")

    assert row["mfg_date_parsed"] == datetime.date(2042, 6, 1)  # parsed exactly as printed
    assert row["dates_valid"] is False  # caught: mfg (2042) is after its own expiry (2026)


def test_an_ordinary_row_is_valid(spark):
    assert parsed(spark, "10/2023", "10/2026")["dates_valid"] is True


def test_formats_not_yet_covered_stay_null_not_guessed(spark):
    # Excel day number, a textual expiry rule, and a placeholder: all deliberately deferred.
    for text in ("45200", "5 Yrs from the date of Mfg.", "NM", "--", None, ""):
        row = parsed(spark, text, "10/2026")
        assert row["mfg_date_parsed"] is None
        assert row["dates_valid"] is None  # can't say valid or invalid: one side is unknown
