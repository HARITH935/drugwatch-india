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
