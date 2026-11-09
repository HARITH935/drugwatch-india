"""Family D: the combined batch / date / maker cell, split at CDSCO's labels (made-up values)."""

import os

import pytest

from drugwatch_extraction.classify import classify_pdf
from drugwatch_extraction.family_d import parse_family_d, split_batch_details
from drugwatch_ingestion.store import RawStore

CELL = "B. No.: CBP-1,\nMfg dt: 12/2017,\nExp dt: 11/2022,\nMfd by: M/s. Test\nLimited (Unit-2)"


def test_splits_a_cell_at_its_labels_keeping_values_as_printed():
    values, problem = split_batch_details(CELL)

    assert values == {
        "batch_no": "CBP-1",  # only the comma separating two labelled parts is dropped
        "mfg_date": "12/2017",
        "expiry_date": "11/2022",
        "manufacturer": "M/s. Test\nLimited (Unit-2)",  # line breaks kept, as in every family
    }
    assert problem is None


def test_a_repeated_label_means_a_multi_part_pack_and_is_not_split():
    two_parts = (
        "For Powder\n" + CELL + "\nFor Diluent\nB. No.: W2,\nMfg dt: 01/2018,\nExp dt: 12/2020"
    )

    values, problem = split_batch_details(two_parts)

    assert values == {}
    assert "appears twice" in problem


def test_a_missing_label_is_not_guessed():
    values, problem = split_batch_details("B. No.: X1, Mfg dt: 01/2018, Mfd by: M/s. Test")

    assert values == {}
    assert "expiry_date" in problem


def test_text_before_the_first_label_is_reported():
    values, problem = split_batch_details("(Powder)\n" + CELL)

    assert values["batch_no"] == "CBP-1"
    assert problem == "text before the first label: '(Powder)'"


def test_parse_keeps_the_original_cell_and_adds_the_split_fields(table_pdf):
    wide = 300  # the combined column is wide, so its one-line text fits the drawn cell
    header = ["Sl. No.", "Name of Drugs", ("Batch No./Date of Manufacture/Date of Expiry", wide),
              "Reason for failure", "Drawn By", "From"]  # fmt: skip
    combined = "B. No.: X1, Mfg dt: 01/2018, Exp dt: 12/2019, Mfd by: M/s. Test"
    row = ["1.", "Test Tablet", (combined, wide), "Assay", "DI, Delhi", "CDL"]

    result = parse_family_d(table_pdf([header, row]))

    fields = result.rows[0].fields
    assert fields["batch_details"] == combined
    assert (fields["batch_no"], fields["expiry_date"], fields["manufacturer"]) == (
        "X1",
        "12/2019",
        "M/s. Test",
    )
    assert result.warnings == []


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_real_2018_lists():
    s3 = RawStore.from_env().s3
    listing = s3.list_objects_v2(Bucket="raw", Prefix="cdsco-pdf/combined/")["Contents"]
    rows = split = 0
    warned = []
    for key in sorted(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf")):
        data = s3.get_object(Bucket="raw", Key=key)["Body"].read()
        if classify_pdf(data).family != "D":
            continue
        result = parse_family_d(data)
        assert (result.serial_gaps, result.unknown_headers, result.skipped) == ([], [], []), key
        rows += len(result.rows)
        split += sum(1 for row in result.rows if row.fields["batch_no"])
        warned += [(key.split("/")[2], index) for index, _ in result.warnings]

    assert (rows, split) == (77, 75)
    assert warned == [("2018-05", 8), ("2018-08", 2)]  # the two two-part packs
