"""label.py: the answers a labeller can give, and the page picture with the row outlined."""

import io

import pdfplumber
import pytest

from drugwatch_extraction.label import Quit, label_fields, row_box, save_picture

RECORD = {
    "family": "B",
    "product_name": "Test Tablets",
    "batch_no": "TB-\n1201",
    "mfg_date": "01/2025",
    "expiry_date": "12/2026",
    "manufacturer": "M/s. Test Pharma",
    "failure_reason": "Assay",
}


def scripted(*answers):
    """An `ask` function that gives these answers in order and records the prompts."""
    remaining, prompts = list(answers), []

    def ask(prompt):
        prompts.append(prompt)
        return remaining.pop(0)

    ask.prompts = prompts
    return ask


def test_enter_keeps_the_value_shown_and_text_replaces_it():
    ask = scripted("", "TB-1201", "/b", "/u", "", "Assay of X", "two-part pack")

    label = label_fields(RECORD, ask)

    assert label == {
        "fields": {
            "product_name": "Test Tablets",  # Enter
            "batch_no": "TB-1201",  # typed
            "mfg_date": "",  # /b: the cell is blank
            "expiry_date": None,  # /u: unreadable
            "manufacturer": "M/s. Test Pharma",
            "failure_reason": "Assay of X",
        },
        "note": "two-part pack",
    }
    assert "TB- ⏎ 1201" in ask.prompts[1]  # line breaks are shown, not hidden


def test_an_unknown_command_asks_again():
    ask = scripted("/x", "", "", "", "", "", "", "")

    label = label_fields(RECORD, ask)

    assert label["fields"]["product_name"] == "Test Tablets"
    assert len(ask.prompts) == 8  # 6 fields + the repeated question + the note


def test_q_stops_without_returning_a_half_label():
    with pytest.raises(Quit):
        label_fields(RECORD, scripted("", "/q"))


def test_the_spurious_layout_is_not_asked_for_a_failure_reason():
    ask = scripted("", "", "", "", "", "")

    label = label_fields(RECORD | {"family": "F"}, ask)

    assert "failure_reason" not in label["fields"]


def test_the_picture_outlines_the_row_with_that_s_no(table_pdf, tmp_path):
    data = table_pdf([["S.No", "Name"], ["1.", "X"], ["2.", "Y"], ["3.", "Z"]])

    with pdfplumber.open(io.BytesIO(data)) as document:
        page = document.pages[0]
        box_2 = row_box(page, "2")
        box_3 = row_box(page, "3")
        assert row_box(page, "9") is None
    assert box_2[1] < box_3[1]  # row 2 sits above row 3
    path = save_picture(data, 1, "2", tmp_path / "pages" / "p1.png")
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # a real PNG file
    plain = save_picture(data, 1, None, tmp_path / "pages" / "p1-plain.png")  # continuation page
    assert plain.read_bytes() != path.read_bytes()  # no outline drawn
