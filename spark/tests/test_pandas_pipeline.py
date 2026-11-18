"""The pandas pipeline, and the comparison that makes the benchmark's claim checkable.

The benchmark says both engines run "the same cleaning job". The first test here is what makes
that a fact rather than a hope: one fixture through both pipelines, compared cell by cell.
"""

import datetime

import numpy as np
import pandas as pd
import pytest
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

from drugwatch_spark import pandas_pipeline as pp
from drugwatch_spark.build_silver import build_silver as spark_build_silver
from drugwatch_spark.compare_engines import canonical, normalised

PDF_ROW = {
    "source_dataset": "central-nsq", "source_key": "bronze/cdsco-pdf/central-nsq/2024-06",
    "source_sha256": "a" * 64, "source_url": "https://cdsco.gov.in/x.pdf",
    "alert_month": "2024-06", "extraction_method": "rule", "batch_no": "TB-1201",
    "mfg_date": "10/2023", "expiry_date": "09/2025",
    "product_name": "Telmisartan Tablets IP 40 mg (TELSAT 40)",
    "manufacturer": "M/s. Test Pharma Ltd., Plot 7, Baddi", "failure_reason": "Assay",
    "reported_by": "CDL Kolkata", "remarks": None, "firm_reply": None, "page": 2, "row_index": 5,
}  # fmt: skip
PORTAL_ROW = {
    "source_dataset": "nsq", "source_key": "bronze/cdsco-portal/nsq/2024-06",
    "source_sha256": "b" * 64, "source_url": "https://cdscoonline.gov.in/p",
    "alert_month": "2024-06", "extraction_method": "api", "batch_no": "PT-9",
    "mfg_date": "Aug-2017", "expiry_date": "Jul-2022", "product_name": None,
    "generic_name": "Paracetamol Tablets IP 500 mg (Pacimol)", "brand_name": "NA",
    "manufacturer": "M/s. Portal Pharma Ltd., Baddi", "failure_reason": "Dissolution",
    "reported_by": "CDL Mumbai", "remarks": None, "firm_reply": None, "row_index": 1,
}  # fmt: skip

PDF_SCHEMA = StructType(
    [
        StructField(name, StringType())
        for name in (
            "source_dataset", "source_key", "source_sha256", "source_url", "alert_month",
            "extraction_method", "batch_no", "mfg_date", "expiry_date", "product_name",
            "manufacturer", "failure_reason", "reported_by", "remarks", "firm_reply",
        )
    ]
    + [StructField("page", IntegerType()), StructField("row_index", IntegerType())]
)  # fmt: skip
PORTAL_SCHEMA = StructType(
    [
        StructField(name, StringType())
        for name in (
            "source_dataset", "source_key", "source_sha256", "source_url", "alert_month",
            "extraction_method", "batch_no", "mfg_date", "expiry_date", "product_name",
            "generic_name", "brand_name", "manufacturer", "failure_reason", "reported_by",
            "remarks", "firm_reply",
        )
    ]
    + [StructField("row_index", IntegerType())]
)  # fmt: skip


def pandas_rows(pdf_over: dict | None = None, portal_over: dict | None = None):
    pdf = pd.DataFrame([{**PDF_ROW, **(pdf_over or {})}])
    portal = pd.DataFrame([{**PORTAL_ROW, **(portal_over or {})}])
    return pdf, portal


def spark_rows(spark, pdf_over: dict | None = None, portal_over: dict | None = None):
    pdf = {**PDF_ROW, **(pdf_over or {})}
    portal = {**PORTAL_ROW, **(portal_over or {})}
    return (
        spark.createDataFrame([tuple(pdf[f.name] for f in PDF_SCHEMA)], PDF_SCHEMA),
        spark.createDataFrame([tuple(portal[f.name] for f in PORTAL_SCHEMA)], PORTAL_SCHEMA),
    )


@pytest.mark.parametrize(
    ("label", "pdf_over", "portal_over"),
    [
        ("ordinary rows", None, None),
        # The combined cell: the portal's own batch_no is stale and the真 values sit in the
        # manufacturer field, with the dates written CDSCO's PDF way.
        (
            "a portal combined cell",
            None,
            {
                "batch_no": "STALE-1",
                "manufacturer": "B. No.: TP-3286,\nMfg dt: 03/2018, Exp dt: 02/2020, "
                "Mfd by: M/s. Ticoma Pharmacia, Baddi",
            },
        ),
        # A spurious report: the manufacturer columns must stay empty on both sides.
        ("a spurious report", {"source_dataset": "spurious"}, None),
        # One company spelled two ways, which only clustering across both sources resolves.
        (
            "one maker, two spellings",
            {"manufacturer": "M/s. Jackson Laboratories Pvt. Ltd., Plot 7, Baddi"},
            {"manufacturer": "Jackson Laboratories Private.Limited, Baddi"},
        ),
        # Deferred date formats, placeholders and mojibake all have to agree too.
        (
            "awkward values",
            {"mfg_date": "29.09.2021", "batch_no": "T?18909"},
            {"batch_no": "Not Applicable"},
        ),  # fmt: skip
    ],
)
def test_both_engines_produce_the_same_silver(spark, label, pdf_over, portal_over):
    spark_out = spark_build_silver(*spark_rows(spark, pdf_over, portal_over)).toPandas()
    pandas_out = pp.build_silver(*pandas_rows(pdf_over, portal_over))

    assert normalised(spark_out) == normalised(pandas_out), label


def test_a_two_digit_year_follows_javas_rule_not_pythons():
    # The one genuine engine difference. Java's `yy` means 2000-2099, so Spark reads "Apr-95" as
    # 2095, which the 1990-2049 plausible-year rule then drops. Python's %y means 1969-2068, so
    # unguarded pandas would read 1995 and KEEP it - the same input giving different output.
    frame = pd.DataFrame([{"mfg_date": "Apr-95", "expiry_date": "Apr-99"}])

    parsed = pp.parse_dates(frame, pp.PDF_DATE_FORMATS)

    assert parsed["mfg_date_parsed"].iloc[0] is None or pd.isna(parsed["mfg_date_parsed"].iloc[0])


def test_a_two_digit_year_inside_the_plausible_range_still_parses():
    frame = pd.DataFrame([{"mfg_date": "Apr-15", "expiry_date": "Apr-20"}])

    parsed = pp.parse_dates(frame, pp.PDF_DATE_FORMATS)

    assert parsed["mfg_date_parsed"].iloc[0] == datetime.date(2015, 4, 1)


def test_every_java_date_format_has_a_python_equivalent():
    # A format added to parse_pdf_dates.py without one here would silently stop being parsed on
    # the pandas side; importing the module fails loudly instead.
    from drugwatch_spark.parse_pdf_dates import FORMATS

    assert set(FORMATS) <= set(pp.JAVA_TO_PYTHON)


def test_whitespace_cleaning_keeps_line_breaks():
    # clean_text.py keeps "\n" on purpose; only horizontal whitespace is collapsed.
    frame = pd.DataFrame([{"batch_no": "  FAB302008 \nFW20-09  "}])

    cleaned = pp.normalize_whitespace(frame, ("batch_no",))

    assert cleaned["batch_no"].iloc[0] == "FAB302008\nFW20-09"


# --- the comparison helper itself -------------------------------------------------------


@pytest.mark.parametrize("missing", [None, float("nan"), np.nan, pd.NA, pd.NaT, np.float64("nan")])
def test_every_flavour_of_missing_becomes_none(missing):
    # The bug this guards: NaN != NaN, so a surviving NaN makes an all-empty column look 100%
    # different on both sides.
    assert canonical(missing) is None


def test_lists_and_arrays_compare_by_value():
    assert canonical(np.array(["40 mg"])) == canonical(["40 mg"]) == ("40 mg",)


def test_an_int_and_a_float_of_the_same_number_are_equal():
    # Spark's int32 page column arrives as float64 once nulls are involved.
    assert canonical(np.int32(2)) == canonical(2.0)


def test_a_midnight_timestamp_equals_the_same_date():
    assert canonical(pd.Timestamp("2024-06-01")) == datetime.date(2024, 6, 1)


def test_a_bool_is_not_turned_into_a_number():
    assert canonical(np.bool_(True)) is True
    assert canonical(False) is False
