"""Family C parser: the header decides the fields (made-up rows, CDSCO's real column names)."""

from drugwatch_extraction.family_c import parse_family_c

BASE = [
    "S.No.",
    "Name of Drugs",  # short enough for the test's 70-point cell (longer text would overflow)
    "Batch No.",
    "Date of Manufacture",
    "Date of Expiry",
    "Manufactured By",
    "Reason for failure",
    "Drawn By",
]


def row(serial, *extra):
    return [
        serial,
        "Test Tablet",
        "SP1",
        "05/2024",
        "04/2026",
        "M/s. Test",
        "Spurious",
        "DI, Delhi",
        *extra,
    ]


def test_columns_follow_each_files_header(table_pdf):
    aug_2024 = parse_family_c(
        table_pdf([[*BASE, "From", "Firm reply"], row("1.", "Zone A", "Denied")])
    )
    sep_2024 = parse_family_c(table_pdf([[*BASE, "Firm reply"], row("1.", "Denied")]))

    assert aug_2024.columns[-2:] == ["drawn_from", "firm_reply"]
    assert aug_2024.rows[0].fields["drawn_from"] == "Zone A"
    assert "remarks" not in sep_2024.columns and "drawn_from" not in sep_2024.columns
    assert sep_2024.rows[0].fields["failure_reason"] == "Spurious"


def test_an_unknown_header_cell_keeps_its_column_and_is_reported(table_pdf):
    result = parse_family_c(table_pdf([[*BASE, "Action Taken"], row("1.", "Recalled")]))

    assert result.unknown_headers == ["other_action_taken"]
    assert result.rows[0].fields["other_action_taken"] == "Recalled"


def test_a_revised_list_can_start_at_any_serial(table_pdf):
    result = parse_family_c(table_pdf([[*BASE, "Firm's reply", "Remarks"], row("23.", "-", "-")]))

    assert (result.first_serial, result.serial_gaps) == (23, [])
    assert result.columns[-2:] == ["firm_reply", "remarks"]
