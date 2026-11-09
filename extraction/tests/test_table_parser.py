"""Rules of the shared table engine that every family relies on."""

from drugwatch_extraction.table_parser import parse_tables

VOCABULARY = (
    ("serial_no", ("s.no",)),
    ("product_name", ("name",)),
    ("batch_no", ("batchno",)),
    ("failure_reason", ("result",)),
    ("drawn_from", ("=from",)),
)


def test_a_row_without_s_no_is_not_a_header(table_pdf):
    result = parse_tables(
        table_pdf([["#", "Name", "Batch No.", "Result", "From"], ["1", "X", "B1", "R", "Z"]]),
        VOCABULARY,
    )

    assert result.columns == [] and result.rows == []
    assert len(result.skipped) == 2  # nothing could be placed, and that is reported


def test_a_header_repeated_on_a_later_page_is_not_read_as_data(table_pdf):
    header = ["S.No", "Name", "Batch No.", "Result", "From"]

    result = parse_tables(
        table_pdf([header, ["1.", "X", "B1", "R", "Z"]], [header, ["2.", "Y", "B2", "R", "Z"]]),
        VOCABULARY,
    )

    assert [r.fields["batch_no"] for r in result.rows] == ["B1", "B2"]
    assert result.skipped == []


def test_an_exact_phrase_matches_only_the_whole_cell(table_pdf):
    header = ["S.No", "Name", "Batch No.", "Result", "Reported from lab"]

    result = parse_tables(table_pdf([header, ["1.", "X", "B1", "R", "CDL"]]), VOCABULARY)

    assert "drawn_from" not in result.columns  # "=from" needs a cell that is exactly "From"
    assert result.unknown_headers == ["other_reported_from_lab"]


def test_a_new_header_replaces_the_column_positions(table_pdf):
    # Page 2 is a separate table whose first column is much wider (like family E's pages): its
    # rows must be read with page 2's header positions, not page 1's.
    page_1 = [["S.No", "Name", "Batch No.", "Result"], ["1.", "X", "B1", "R1"]]
    page_2 = [[("S.No", 150), "Name", "Batch No.", "Result"], [("2.", 150), "Y", "B2", "R2"]]

    result = parse_tables(table_pdf(page_1, page_2), VOCABULARY)

    assert [(r.fields["product_name"], r.fields["batch_no"]) for r in result.rows] == [
        ("X", "B1"),
        ("Y", "B2"),
    ]


def test_overprinted_text_is_kept_but_warned_about(table_pdf):
    header = ["S.No", "Name", "Batch No.", "Result"]
    garbled = ["1.", ["Test Pharma", "20100901"], "B1", "R"]  # two texts drawn on the same spot

    result = parse_tables(table_pdf([header, garbled, ["2.", "Y", "B2", "R"]]), VOCABULARY)

    assert len(result.rows) == 2  # the row is kept, as extracted
    assert result.warnings == [
        (1, "product_name: overprinted text (two texts drawn on top of each other)")
    ]


def test_one_overlapping_pair_or_bold_printing_is_not_overprint(table_pdf):
    header = ["S.No", "Name", "Batch No.", "Result"]
    one_pair = ["1.", ["X", "Y"], "B1", "R"]  # a single collision: could just be a tight font
    bold = ["2.", ["Bold", "Bold"], "B2", "R"]  # the same letters drawn twice

    result = parse_tables(table_pdf([header, one_pair, bold]), VOCABULARY)

    assert len(result.rows) == 2 and result.warnings == []
