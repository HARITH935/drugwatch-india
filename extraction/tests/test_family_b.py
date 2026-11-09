"""Family B parser, on PDFs the tests build themselves (made-up rows, CDSCO's real column names)."""

from drugwatch_extraction.family_b import FIELDS, parse_family_b

HEADER = [
    "S.No",
    "Product/Drug Name",
    "Batch No.",
    "Manufacturing Date",
    "Expiry Date",
    "Manufactured By",
    "NSQ Result",
    "Reported by",
]


def row(serial, name="Test Tablet", batch="TB1", maker="M/s. Test Pharma", result="Assay"):
    return [serial, name, batch, "01/2025", "12/2026", maker, result, "CDL, Kolkata"]


def continuation(name="", maker=""):
    return ["", name, "", "", "", maker, "", ""]


def test_reads_numbered_rows_into_named_fields(table_pdf):
    result = parse_family_b(table_pdf([HEADER, row("1."), row("2.", batch="TB2")]))

    assert [r.fields["batch_no"] for r in result.rows] == ["TB1", "TB2"]
    first = result.rows[0]
    assert set(first.fields) == set(FIELDS)
    assert (first.row_index, first.page, first.pages, first.section) == (1, 1, (1,), None)
    assert result.serial_gaps == [] and result.skipped == []


def test_short_date_headers_name_the_date_fields(table_pdf):
    # Apr 2024's state-lab pages print "Mfg Dt" / "Exp Dt" instead of the long names.
    header = [*HEADER[:3], "Mfg Dt", "Exp Dt", *HEADER[5:]]

    result = parse_family_b(table_pdf([header, row("1.")]))

    assert result.unknown_headers == []
    assert (result.rows[0].fields["mfg_date"], result.rows[0].fields["expiry_date"]) == (
        "01/2025",
        "12/2026",
    )


def test_remembers_section_rows(table_pdf):
    section = ["B. State Laboratories", "", "", "", "", "", "", ""]

    result = parse_family_b(table_pdf([section, HEADER, row("1.")]))

    assert result.rows[0].section == "B. State Laboratories"


def test_merges_a_row_cut_by_a_page_break(table_pdf):
    page_1 = [HEADER, row("1."), row("2.", maker="M/s. Test Pharma Pvt.")]
    page_2 = [continuation(maker="Ltd., Plot 7, Baddi"), row("3.")]

    result = parse_family_b(table_pdf(page_1, page_2))

    second = result.rows[1]
    assert second.fields["manufacturer"] == "M/s. Test Pharma Pvt.\nLtd., Plot 7, Baddi"
    assert second.pages == (1, 2)
    assert len(result.rows) == 3


def test_does_not_repeat_lines_the_row_already_has(table_pdf):
    pdf = table_pdf(
        [HEADER, row("1.", maker="M/s. Test Pharma"), continuation(maker="M/s. Test Pharma")]
    )

    assert parse_family_b(pdf).rows[0].fields["manufacturer"] == "M/s. Test Pharma"


def test_aligns_split_cells_by_position(table_pdf):
    # Page 2 is drawn with the name column split into 3 narrow cells (70 = 23 + 23 + 24), like
    # CDSCO's Apr 2024 page 4. Each piece must still land in product_name, not shift the columns.
    split_row = ["4.", ("", 23), ("Cyclo", 23), ("", 24), "TB4", "01/2025", "12/2026",
                 "M/s. Test Pharma", "Water", "CDL, Kolkata"]  # fmt: skip

    result = parse_family_b(table_pdf([HEADER, row("3.")], [split_row]))

    fourth = result.rows[1]
    assert fourth.fields["product_name"] == "Cyclo"  # short enough to fit its narrow cell
    assert fourth.fields["batch_no"] == "TB4"
    assert fourth.fields["failure_reason"] == "Water"


def test_a_footnote_box_is_reported_not_glued_onto_the_last_row(table_pdf):
    # Like CDSCO's: a 1-column box with 2 rows (pdfplumber doesn't count a single box as a table).
    footnote_page = [
        [("(Further, the samples were declared not of standard quality", 560)],
        [("under the Drugs and Cosmetics Act.)", 560)],
    ]

    result = parse_family_b(table_pdf([HEADER, row("1.")], footnote_page))

    assert result.rows[0].fields["failure_reason"] == "Assay"  # not glued onto the last record
    assert [why for _, why, _ in result.skipped] == ["1 columns", "1 columns"]


def test_reports_unrecognised_rows_and_serial_gaps(table_pdf):
    note = ["Note:", "see annexure", "", "", "", "", "", ""]

    result = parse_family_b(table_pdf([HEADER, row("1."), note, row("3.")]))

    assert [why for _, why, _ in result.skipped] == ["row not recognised"]
    assert result.serial_gaps == [2]
