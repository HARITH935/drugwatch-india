"""fix_portal_batch.py: the same cut-at-labels rule as family_d.py, applied to portal rows."""

from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.fix_portal_batch import (
    SPLIT_FIELDS,
    combined_cell_rows,
    fix_combined_manufacturer_cells,
    split_combined_cell,
)

CELL = "B. No.: CBP-1,\nMfg dt: 12/2017,\nExp dt: 11/2022,\nMfd by: M/s. Test\nLimited (Unit-2)"
# A real example from the portal (alert_month 2019-01): the finding that started this module.
REAL_CELL = (
    "B. No.:  PT-180905,\nMfg dt:  09/2018, Exp dt:   08/2019, Mfd by: M/s. Panther\n"
    "Health Care Pvt. Ltd., Plot\nNo.318, Madhopur Road, Saliyar, Dehradun Road, "
    "Roorkee-247667 (U.K.)."
)


def test_splits_a_cell_at_its_labels_keeping_values_as_printed():
    assert split_combined_cell(CELL) == {
        "batch_no": "CBP-1",  # only the comma separating two labelled parts is dropped
        "mfg_date": "12/2017",
        "expiry_date": "11/2022",
        "manufacturer": "M/s. Test\nLimited (Unit-2)",  # line breaks kept
    }


def test_the_real_portal_example_that_found_this_bug():
    values = split_combined_cell(REAL_CELL)

    assert values["batch_no"] == "PT-180905"  # the portal's own str_batch_no said "8S17004,": wrong
    assert (values["mfg_date"], values["expiry_date"]) == ("09/2018", "08/2019")
    assert values["manufacturer"].startswith("M/s. Panther\nHealth Care Pvt. Ltd.")


def test_a_double_comma_before_the_next_label_is_fully_removed():
    # Real example (alert_month 2019-01, batch AHT-1239): a stray second comma, with extra spaces,
    # sits before "Exp dt:". A single removesuffix(",") would leave "08/2018," - still has a comma.
    cell = (
        "B. No.: AHT-1239,\nMfg dt: 08/2018,               , Exp dt: 07/2020 ,\nMfd by: M/s. Test"
    )

    values = split_combined_cell(cell)

    assert values["mfg_date"] == "08/2018"  # not "08/2018,"
    assert values["expiry_date"] == "07/2020"


def test_a_repeated_label_is_not_split():
    two_parts = (
        "For Powder\n" + CELL + "\nFor Diluent\nB. No.: W2,\nMfg dt: 01/2018,\nExp dt: 12/2020"
    )

    assert split_combined_cell(two_parts) == dict.fromkeys(SPLIT_FIELDS)


def test_a_missing_label_is_not_guessed():
    assert split_combined_cell("B. No.: X1, Mfg dt: 01/2018, Mfd by: M/s. Test") == dict.fromkeys(
        SPLIT_FIELDS
    )


def test_an_ordinary_manufacturer_value_is_not_split():
    assert split_combined_cell("M/s. Test Pharma, Plot 7, Baddi") == dict.fromkeys(SPLIT_FIELDS)


def test_none_and_empty_are_not_split():
    assert split_combined_cell(None) == dict.fromkeys(SPLIT_FIELDS)
    assert split_combined_cell("") == dict.fromkeys(SPLIT_FIELDS)


def _schema():
    names = ["batch_no", "mfg_date", "expiry_date", "manufacturer", "alert_month"]
    return StructType([StructField(n, StringType()) for n in names])


def test_a_combined_row_is_corrected_in_place(spark):
    row = ("8S17004,", "ignored", "ignored", REAL_CELL, "2019-01")
    df = spark.createDataFrame([row], _schema())

    fixed = fix_combined_manufacturer_cells(df).collect()[0]

    assert fixed["batch_no"] == "PT-180905"
    assert (fixed["mfg_date"], fixed["expiry_date"]) == ("09/2018", "08/2019")
    assert fixed["manufacturer"].startswith("M/s. Panther")


def test_an_ordinary_row_is_left_exactly_as_it_was(spark):
    row = ("TB1201", "01/2025", "12/2026", "M/s. Test Pharma, Baddi", "2025-06")
    df = spark.createDataFrame([row], _schema())

    fixed = fix_combined_manufacturer_cells(df).collect()[0]

    assert (fixed["batch_no"], fixed["manufacturer"]) == ("TB1201", "M/s. Test Pharma, Baddi")


def test_combined_cell_rows_flags_only_the_affected_rows(spark):
    df = spark.createDataFrame(
        [
            ("8S17004,", "x", "x", REAL_CELL, "2019-01"),
            ("TB1201", "01/2025", "12/2026", "M/s. Test Pharma, Baddi", "2025-06"),
        ],  # fmt: skip
        _schema(),
    )

    flags = [row["flag"] for row in df.withColumn("flag", combined_cell_rows(df)).collect()]

    assert flags == [True, False]
