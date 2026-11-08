"""PDF classification: text vs scanned, and the layout family from header cells."""

import pytest

from drugwatch_extraction.classify import PageStats, classify_pdf, layout_family, page_kind

# Header cells as CDSCO prints them (column names only, no alert data), with their real quirks.
HEADERS = {
    "A": ["S.No.", "Vaccine Name", "Batch No.", "Manufacturing Date", "NSQ Result"],
    "B-2024": ["B. State Laboratories", "Name of Drugs/medical device/cosmetics", "NSQ Result"],
    "B-2025": ["S.No", "Product/Drug\nName", "Manufactu ring Date", "NSQ Result"],
    "C": ["S.No.", "Name of Drugs/medical device", "Reason for\nfailure", "Drawn By", "Remarks"],
    "D": ["Sl. No.", "Batch No./Date of Manufacture", "Reason for failure", "Drawn By", "From"],
    "E": ["Detail of samples declared NSQ by CDL", "REGULATORY ACTION/ Sample status"],
    "F": ["NCT of DELHI", "Product/Drug Name", "Sales outlets involved in distribution",
          "Response of original manufacturer"],
}  # fmt: skip


@pytest.mark.parametrize(
    ("chars", "image_cover", "kind"),
    [(50, 0.0, "text"), (49, 0.9, "scanned"), (0, 0.5, "blank"), (3, 0.0, "blank")],
)
def test_page_kind(chars, image_cover, kind):
    assert page_kind(PageStats(chars, image_cover)) == kind


@pytest.mark.parametrize(
    ("header", "family"),
    [
        ("A", "A"),
        ("B-2024", "B"),  # both CDSCO vocabularies for the same columns
        ("B-2025", "B"),  # words broken by line breaks still match
        ("C", "C"),
        ("D", "D"),  # also has C's words: the more specific rule must win
        ("E", "E"),
        ("F", "F"),  # also has B's "Product/Drug Name", but no "NSQ Result"
    ],
)
def test_layout_family(header, family):
    assert layout_family(HEADERS[header]) == family


def test_a_new_layout_is_unknown_not_guessed():
    assert layout_family(["S.No", "Medicine", "Lot", "Outcome"]) == "unknown"


def test_words_from_two_cells_never_form_one_phrase():
    # "NSQ" ends one cell and "Result" starts the next: that is not the header "NSQ Result".
    assert layout_family(["Product/Drug Name", "NSQ", "Result"]) == "unknown"


def test_classify_a_real_pdf_end_to_end(table_pdf):
    pdf = table_pdf(
        [
            ["S.No", "Product/Drug Name", "Batch No.", "Expiry Date", "NSQ Result"],
            ["1", "Test Tablet 500 mg", "TB001", "01/2027", "Fails assay"],
        ],
        blank_pages=1,
    )

    result = classify_pdf(pdf)

    assert result.family == "B"
    assert result.pages == 2
    assert result.page_kinds == {"text": 1, "scanned": 0, "blank": 1}
    assert result.readable
