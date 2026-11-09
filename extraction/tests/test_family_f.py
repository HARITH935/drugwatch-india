"""Family F parser: state groups as sections, and its own columns (made-up rows)."""

import os

import pytest

from drugwatch_extraction.family_f import parse_family_f
from drugwatch_ingestion.store import RawStore

HEADER = [
    "S. No.",
    "Product/Drug Name",
    "B. No.",
    "Manufacturing Date",
    "Expiry Date",
    "Manufactured by",
    "Sales Outlets",
    "Response of Original",
    "Reported by",
]


def state(name):
    return [name, "", "", "", "", "", "", "", ""]


def row(serial, batch):
    return [
        serial,
        "Test Tablet",
        batch,
        "Feb.2023",
        "Sep.2026",
        "Genuine Co.",
        "M/s. Shop",
        "Not ours",
        "SLA",
    ]


def test_state_rows_become_sections_and_new_columns_are_named(table_pdf):
    pdf = table_pdf(
        [state("NCT of DELHI"), HEADER, row("1", "SP1"), state("JHARKHAND"), row("2", "SP2")]
    )

    result = parse_family_f(pdf)

    assert [r.section for r in result.rows] == ["NCT of DELHI", "JHARKHAND"]
    assert result.rows[0].fields["batch_no"] == "SP1"  # "B. No." is the batch column
    assert result.rows[0].fields["sales_outlets"] == "M/s. Shop"
    assert result.rows[0].fields["manufacturer_response"] == "Not ours"
    assert result.unknown_headers == []


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_real_april_2024_file():
    s3 = RawStore.from_env().s3
    listing = s3.list_objects_v2(Bucket="raw", Prefix="cdsco-pdf/spurious/2024-04/")["Contents"]
    key = next(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf"))

    result = parse_family_f(s3.get_object(Bucket="raw", Key=key)["Body"].read())

    assert [r.section for r in result.rows] == ["NCT of DELHI"] * 4 + ["JHARKHAND"]
    assert (result.serial_gaps, result.unknown_headers, result.skipped) == ([], [], [])
