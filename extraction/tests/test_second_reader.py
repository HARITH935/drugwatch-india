"""second_reader.py: where the row picture is cut, and how two readings are compared."""

import io

import pdfplumber
import pytest

from drugwatch_extraction.family_b import VOCABULARY
from drugwatch_extraction.second_reader import compare, render_row, row_strips

B_HEADER = ["S.No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date",
            "Manufactured By", "NSQ Result", "Reported by"]  # fmt: skip
FIELDS = ("product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer", "failure_reason")


def row(serial, batch="TB1", maker="M/s. Test"):
    return [serial, "Tablet", batch, "01/2025", "12/2026", maker, "Assay", "CDL"]


def test_the_picture_has_the_header_the_row_its_sub_rows_and_its_continuation(table_pdf):
    page_1 = [B_HEADER, row("1."), row("2."), ["", "", "", "", "", "Plot 7,", "", ""]]
    page_2 = [["", "", "", "", "", "Baddi", "", ""], row("3.")]
    data = table_pdf(page_1, page_2)

    with pdfplumber.open(io.BytesIO(data)) as document:
        strips = row_strips(document, 1, "2", [1, 2], VOCABULARY)

    assert [page for page, _ in strips] == [1, 1, 2]  # header, row 2, continuation
    (_, header), (_, own), (_, rest) = strips
    assert round(header[3] - header[1]) == 20  # one table row high (the test PDF's row height)
    assert round(own[3] - own[1]) == 40  # row 2 plus the unnumbered row under it
    assert round(rest[3] - rest[1]) == 20  # only the top row of page 2, not row 3
    assert render_row(data, 1, "2", [1, 2], "B").height > 0


def test_a_missing_row_is_reported(table_pdf):
    with pdfplumber.open(io.BytesIO(table_pdf([B_HEADER, row("1.")]))) as document:
        with pytest.raises(LookupError, match="S.No 9"):
            row_strips(document, 1, "9", [1], VOCABULARY)


def test_readings_agree_when_only_spaces_and_line_breaks_differ():
    record = dict(
        zip(
            FIELDS, ("Tablet", "TB-\n1201", "01/2025", "12/2026", "M/s. Test", "Assay"), strict=True
        )
    )
    reading = {
        "row": 1,
        "fields": dict(record) | {"batch_no": "TB- 1201", "failure_reason": "Assay of X"},
    }

    agreed, differ = compare({"family": "B"}, reading, record)

    assert agreed["batch_no"] == "TB-\n1201"  # the label keeps the value as extracted
    assert differ == {"failure_reason": {"parser": "Assay", "second_reader": "Assay of X"}}


def test_unreadable_or_a_row_the_parser_lost_goes_to_a_person():
    reading = {"row": 1, "fields": dict.fromkeys(FIELDS, "X") | {"batch_no": None}}

    _, differ = compare({"family": "B"}, reading, None)  # no bronze record for this row

    assert set(differ) == set(FIELDS)
    assert differ["batch_no"] == {"parser": "", "second_reader": None}


def test_a_reading_with_the_wrong_fields_is_refused():
    with pytest.raises(ValueError, match="need"):
        compare({"family": "F"}, {"row": 7, "fields": dict.fromkeys(FIELDS, "X")}, {})
