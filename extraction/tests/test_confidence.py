"""The confidence flag (made-up values in the shapes the archive really prints)."""

import pytest

from drugwatch_extraction.confidence import assess, field_problem


def record(**overrides):
    return {
        "family": "B",
        "product_name": "Test Tablets IP 500 mg",
        "batch_no": "TB-1201",
        "mfg_date": "01/2025",
        "expiry_date": "Dec-2026",
        "manufacturer": "M/s. Test Pharma, Plot 7, Baddi",
        "failure_reason": "Assay",
        "warnings": [],
    } | overrides


def test_a_complete_well_formed_row_is_high():
    assert assess(record()) == ("high", [])


@pytest.mark.parametrize(
    "value",
    [
        "03/2025",
        "12/2022.",  # trailing dot
        "Mar-2025",
        "Feb'16",
        "June. 2023",
        "June, 2023",
        "01-Jan-2024",
        "22.01.2\n024",  # broken across lines inside the cell
        "Dec/202\n3",
        "0 9 / 2 0 2 4 .",  # letter-spaced
        "F e b - 2 5",
        "Apr--2026",
        "Sept-2025",
    ],
)
def test_printed_date_variants_are_dates(value):
    assert field_problem("mfg_date", value) is None


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("3 Yrs from\nthe date of\nMfg.", "not a date"),  # a rule, not a date
        ("Best\nBefore 36\nMonths", "not a date"),
        ("Feb-15\nFeb-16", "not a date"),  # two dates in one cell
        ("30-062025", "not a date"),
        ("13/2025", "not a date"),  # no month 13
        ("Smarch-2025", "not a date"),
        ("45200", "Excel day number"),  # 1 Oct 2023 as a spreadsheet stores it
        ("NIL", "not stated"),
        ("Not\nMentioned", "not stated"),
        ("--", "not stated"),
        ("", "missing"),
        (None, "missing"),
    ],
)
def test_what_is_not_a_well_formed_date(value, problem):
    assert field_problem("expiry_date", value) == problem


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("TB-1201", None),
        ("D\n2615/24-\n25", None),  # wrapped onto three lines
        ("TB1201,", None),  # a trailing comma is not a second batch
        ("TB1201C,\nTB-1201B", "several values"),  # which batch failed?
        ("Not\nmentioned", "not stated"),
        ("ABCD", "no digit"),
    ],
)
def test_batch_numbers(value, problem):
    assert field_problem("batch_no", value) == problem


def test_a_manufacturer_cell_saying_spurious_names_no_manufacturer():
    assert field_problem("manufacturer", "Spurious") == "not stated"
    assert field_problem("manufacturer", "N/A") == "not stated"


def test_every_reason_is_listed():
    low = record(batch_no="NIL", mfg_date="45200", expiry_date="", warnings=["a parser problem"])

    assert assess(low) == (
        "low",
        [
            "batch_no: not stated",
            "mfg_date: Excel day number",
            "expiry_date: missing",
            "parser warning",
        ],
    )


def test_failure_reason_is_required_except_in_the_spurious_layout():
    without_reason = {k: v for k, v in record().items() if k != "failure_reason"}

    assert assess(without_reason) == ("low", ["failure_reason: missing"])
    assert assess(without_reason | {"family": "F"}) == ("high", [])  # F has no such column
