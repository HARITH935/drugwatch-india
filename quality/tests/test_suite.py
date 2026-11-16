"""The suite has to FAIL on bad silver, not just pass on good silver.

A quality gate that only ever goes green is indistinguishable from no gate at all, so every test
below breaks one rule and asserts that its own expectation caught it.

The row-count rule (7,000-15,000) can never hold for a three-row fixture, so these tests check
the outcome of the specific expectation under test rather than the overall result.
"""

import datetime

import pandas as pd
import pytest

from drugwatch_quality.suite import validate

GOOD = {
    "source_key": "bronze/cdsco-portal/nsq/2025-06",
    "source_sha256": "a" * 64,
    "source_url": "https://cdscoonline.gov.in/x",
    "page": None,
    "row_index": 1,
    "extraction_method": "api",
    "also_reported_in": [],
    "alert_month": "2025-06",
    "source_dataset": "nsq",
    "batch_no": "TB-1201",
    "batch_no_raw": "TB-1201",
    "product_name_raw": "Paracetamol Tablets IP 500 mg",
    "mfg_date": datetime.date(2023, 10, 1),
    "expiry_date": datetime.date(2025, 9, 1),
    "dates_valid": True,
    "manufacturer_raw": "M/s. Test Pharma Ltd., Baddi",
    "manufacturer_name": "Test Pharma Limited",
    "manufacturer_address": "Baddi",
    "manufacturer_canonical": "Test Pharma Limited",
    "is_spurious": False,
    "name_on_pack": None,
    "failure_reason": "Dissolution",
    "failure_categories": ["Dissolution"],
}


def frame(*overrides: dict) -> pd.DataFrame:
    """A small silver-shaped frame; each override becomes one row on top of GOOD."""
    rows = [{**GOOD, **over} for over in (overrides or ({},))]
    for index, row in enumerate(rows):  # keep the compound key unique unless a test breaks it
        row.setdefault("row_index", index + 1)
    return pd.DataFrame(rows)


def outcome(result, expectation: str, column: str | None = None):
    """The result of one expectation, by type and column."""
    for item in result.results:
        config = item.expectation_config
        if config.type != expectation:
            continue
        if column is None or config.kwargs.get("column") == column:
            return item
    raise AssertionError(f"no {expectation} for {column} in the suite")


def test_good_rows_pass_every_rule_except_the_row_count(spark_free_result):
    failures = [
        item.expectation_config.type for item in spark_free_result.results if not item.success
    ]

    assert failures == ["expect_table_row_count_to_be_between"]


@pytest.fixture
def spark_free_result():
    return validate(frame({"row_index": 1}, {"row_index": 2}))


# --- the spurious rule (CLAUDE.md Section 6) --------------------------------------------


def test_it_catches_a_spurious_row_attributed_to_a_manufacturer():
    # The single most important check in the suite: a spurious alert names the company on a FAKE
    # pack, so attributing it would accuse a counterfeiting victim.
    bad = frame(
        {
            "is_spurious": True,
            "manufacturer_canonical": "Ipca Laboratories Limited",
            "manufacturer_name": None,
            "manufacturer_address": None,
            "name_on_pack": "Ipca Laboratories Limited",
        }
    )

    result = validate(bad)

    assert not outcome(result, "expect_column_values_to_be_null", "manufacturer_canonical").success


def test_it_catches_a_cleaned_manufacturer_name_left_on_a_spurious_row():
    bad = frame({"is_spurious": True, "manufacturer_canonical": None,
                 "manufacturer_name": "Ipca Laboratories Limited", "manufacturer_address": None,
                 "name_on_pack": "Ipca Laboratories Limited"})  # fmt: skip

    result = validate(bad)

    assert not outcome(result, "expect_column_values_to_be_null", "manufacturer_name").success


def test_it_catches_a_name_on_pack_on_an_ordinary_row():
    # name_on_pack is only meaningful on a counterfeit report; elsewhere it would imply one.
    result = validate(frame({"is_spurious": False, "name_on_pack": "Some Pharma Limited"}))

    assert not outcome(result, "expect_column_values_to_be_null", "name_on_pack").success


# --- vocabularies -----------------------------------------------------------------------


def test_it_catches_a_failure_category_outside_the_vocabulary():
    # This is what fires if someone edits the category list in the pipeline: the suite
    # restates the expected values independently, so the two drifting apart is a failure,
    # not a silent change.
    result = validate(frame({"failure_categories": ["Dissolution", "Smell"]}))

    assert not outcome(result, "expect_column_max_to_be_between", "unknown_categories").success


def test_it_catches_a_row_with_no_category_at_all():
    # An unplaceable reason must become ["Other"], never an empty list.
    result = validate(frame({"failure_categories": []}))

    assert not outcome(result, "expect_column_min_to_be_between", "category_count").success


@pytest.mark.parametrize(
    ("column", "bad_value"),
    [("extraction_method", "guess"), ("source_dataset", "nsq-bulk")],
)
def test_it_catches_an_unknown_value_in_a_fixed_vocabulary(column, bad_value):
    # "nsq-bulk" specifically: step 7 drops that redundant file, so its reappearance is a bug.
    result = validate(frame({column: bad_value}))

    assert not outcome(result, "expect_column_values_to_be_in_set", column).success


# --- provenance -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "source_key",
        "source_sha256",
        "source_url",
        "alert_month",
        "batch_no",
        "product_name_raw",
        "manufacturer_raw",
        "extraction_method",
    ],  # fmt: skip
)
def test_it_catches_a_missing_required_field(column):
    result = validate(frame({column: None}))

    assert not outcome(result, "expect_column_values_to_not_be_null", column).success


def test_it_catches_a_hash_that_is_not_a_sha256():
    result = validate(frame({"source_sha256": "not-a-hash"}))

    assert not outcome(result, "expect_column_values_to_match_regex", "source_sha256").success


@pytest.mark.parametrize("bad_month", ["2025-13", "202506", "June 2025", "2025-6"])
def test_it_catches_a_malformed_alert_month(bad_month):
    result = validate(frame({"alert_month": bad_month}))

    assert not outcome(result, "expect_column_values_to_match_regex", "alert_month").success


def test_it_catches_the_same_row_written_twice():
    # The proof that de-duplication (step 7) did not leave a finding in silver twice.
    duplicate = {"source_key": "bronze/cdsco-pdf/state-nsq/2025-06", "page": 2, "row_index": 5}

    result = validate(frame(duplicate, duplicate))

    assert not outcome(result, "expect_compound_columns_to_be_unique").success


# --- dates ------------------------------------------------------------------------------


def test_it_catches_an_impossible_year():
    # parse_dates.py nulls anything outside 1990-2049 after Java's parser read "Apr--2026" as
    # the year -2026; this is the check that would catch such a value reaching silver.
    result = validate(frame({"mfg_date": datetime.date(1850, 1, 1)}))

    assert not outcome(result, "expect_column_values_to_be_between", "mfg_date_year").success


def test_it_tolerates_the_17_real_cdsco_date_typos_but_not_a_broken_parser():
    # 17 of 7,128 real rows print mfg_date on or after expiry_date. One such row in a hundred
    # passes; a parser inverting dates wholesale does not.
    one_bad = [{"dates_valid": True}] * 99 + [{"dates_valid": False}]
    many_bad = [{"dates_valid": False}] * 50 + [{"dates_valid": True}] * 50

    assert outcome(validate(frame(*one_bad)), "expect_column_values_to_be_in_set",
                   "dates_valid").success  # fmt: skip
    assert not outcome(validate(frame(*many_bad)), "expect_column_values_to_be_in_set",
                       "dates_valid").success  # fmt: skip


# --- the batch number -------------------------------------------------------------------


def test_a_batch_number_with_mojibake_or_a_line_break_still_passes():
    # Real values: 22 carry mojibake where a dash was mangled, 62 contain a line break. They are
    # correct rows, so the suite deliberately has no format rule beyond "has some text".
    result = validate(frame({"batch_no": "T?18909"}, {"batch_no": "FAB302008\nFW20-09"}))

    assert outcome(result, "expect_column_values_to_match_regex", "batch_no").success


def test_it_catches_batch_numbers_going_blank_wholesale():
    # 7 of 7,128 real rows have no letter or digit, which the 99.9% threshold allows. A parser
    # that stopped reading the column at all does not slip through.
    result = validate(frame(*([{"batch_no": "--"}] * 10)))

    assert not outcome(result, "expect_column_values_to_match_regex", "batch_no").success
