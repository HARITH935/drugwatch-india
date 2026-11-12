"""label.py: the answers a labeller can give, and the page picture with the row outlined."""

import io

import pdfplumber
import pytest

from drugwatch_extraction.label import (
    MIN_SECONDS,
    Quit,
    label_fields,
    review_fields,
    row_box,
    save_picture,
)

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


def clock(*times):
    """A fake clock: each call returns the next time (in seconds)."""
    remaining = list(times)
    return lambda: remaining.pop(0)


CAREFUL = (0, MIN_SECONDS + 10)  # the row took long enough to have been checked


def test_enter_keeps_the_value_shown_and_text_replaces_it():
    ask = scripted("", "TB-1201", "/b", "/u", "", "Assay of X", "two-part pack")

    label = label_fields(RECORD, ask, clock(*CAREFUL))

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

    label = label_fields(RECORD, ask, clock(*CAREFUL))

    assert label["fields"]["product_name"] == "Test Tablets"
    assert len(ask.prompts) == 8  # 6 fields + the repeated question + the note


def test_q_stops_without_returning_a_half_label():
    with pytest.raises(Quit):
        label_fields(RECORD, scripted("", "/q"), clock(*CAREFUL))


def test_the_spurious_layout_is_not_asked_for_a_failure_reason():
    ask = scripted("", "", "", "", "", "")

    label = label_fields(RECORD | {"family": "F"}, ask, clock(*CAREFUL))

    assert "failure_reason" not in label["fields"]


def test_a_row_answered_too_fast_is_asked_again(capsys):
    # First try: 7 Enters in 2 seconds (not checked). Second try: typed with care.
    ask = scripted(*[""] * 7, "", "TB-1201", "", "", "", "", "")

    label = label_fields(RECORD, ask, clock(0, 2, 2, 2 + MIN_SECONDS + 10))

    assert label["fields"]["batch_no"] == "TB-1201"  # the second, careful answers are kept
    assert len(ask.prompts) == 14  # the whole row was asked twice
    assert "too fast" in capsys.readouterr().out


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


DIFFER = {
    "batch_no": {"parser": "TB-1201", "second_reader": "TB-1207"},
    "failure_reason": {"parser": "Light Absortion", "second_reader": "Light Absorption"},
    "manufacturer": {"parser": "2M0/s1 0B0i", "second_reader": None},
}


def test_review_takes_1_2_or_a_typed_value_and_records_who_decided():
    ask = scripted("2", "1", "M/s. Test Pharma")

    decided = review_fields(DIFFER, ask, clock(*CAREFUL))

    assert decided == {
        "fields": {
            "batch_no": "TB-1207",
            "failure_reason": "Light Absortion",  # the PDF's own typo, kept
            "manufacturer": "M/s. Test Pharma",
        },
        "decided": {
            "batch_no": "second_reader",
            "failure_reason": "parser",
            "manufacturer": "typed",
        },
    }


def test_review_asks_again_for_an_empty_answer_and_stops_on_q():
    ask = scripted("", "1", "/q")

    with pytest.raises(Quit):
        review_fields(DIFFER, ask, clock(*CAREFUL))
    assert len(ask.prompts) == 3  # Enter alone is not an answer here


def test_a_review_answered_too_fast_is_asked_again():
    ask = scripted("1", "1", "1", "2", "1", "/b")

    decided = review_fields(DIFFER, ask, clock(0, 1, 1, 1 + MIN_SECONDS + 10))

    assert decided["fields"] == {"batch_no": "TB-1207", "failure_reason": "Light Absortion",
                                 "manufacturer": ""}  # fmt: skip
