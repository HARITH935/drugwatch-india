"""extract.py: classify, parse, attach provenance (self-built PDFs and made-up sidecars)."""

import hashlib
import os
import re
from collections import Counter

import pytest

from drugwatch_extraction.extract import extract_pdf, records_for
from drugwatch_ingestion.store import RawStore

B_HEADER = ["S.No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date",
            "Manufactured By", "NSQ Result", "Reported by"]  # fmt: skip


def sidecar_for(data: bytes, **overrides) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    return {
        "key": f"cdsco-pdf/central-nsq/2025-06/12927/{sha}.pdf",
        "sha256": sha,
        "dataset": "central-nsq",
        "alert_month": "2025-06",
        "file_id": "12927",
        "listing": {"title": "NSQ ALERT FOR THE MONTH OF June 2025"},
        "request": {"final_url": "https://cdsco.gov.in/opencms/resources/test.pdf"},
    } | overrides


def b_pdf(table_pdf):
    row = ["1.", "Test Tablet", "TB1", "01/2025", "12/2026", "M/s. Test", "Assay", "CDL"]
    return table_pdf([B_HEADER, row, ["2.", *row[1:2], "TB2", *row[3:]]])


def test_every_record_carries_its_provenance(table_pdf):
    data = b_pdf(table_pdf)

    result = records_for(data, sidecar_for(data))

    assert result.problem is None and result.family == "B"
    first = result.records[0]
    assert first["batch_no"] == "TB1"  # the row's own fields...
    assert first["source_key"].startswith("cdsco-pdf/central-nsq/2025-06/12927/")  # ...plus origin
    assert first["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert first["source_url"] == "https://cdsco.gov.in/opencms/resources/test.pdf"
    assert (first["alert_month"], first["file_id"], first["family"]) == ("2025-06", "12927", "B")
    assert (first["page"], first["row_index"], first["extraction_method"]) == (1, 1, "rule")
    assert result.records[1]["row_index"] == 2
    assert first["warnings"] == []


def test_bytes_that_dont_match_the_sidecar_give_no_records(table_pdf):
    data = b_pdf(table_pdf)

    result = records_for(data, sidecar_for(data, sha256="0" * 64))

    assert result.records == []
    assert "SHA-256" in result.problem


def test_an_unknown_layout_is_reported_not_guessed(table_pdf):
    data = table_pdf([["S.No", "Medicine", "Lot", "Outcome"], ["1", "X", "L1", "Fail"]])

    result = records_for(data, sidecar_for(data))

    assert result.records == []
    assert result.problem == "layout family 'unknown': no parser"


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_whole_archive_extracts_with_full_provenance():
    s3 = RawStore.from_env().s3
    keys = sorted(
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket="raw", Prefix="cdsco-pdf/")
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".pdf")
    )
    records, families = [], Counter()
    for key in keys:
        result = extract_pdf(s3, key)
        assert result.problem is None, key
        families[result.family] += len(result.records)
        records += result.records

    assert (len(keys), len(records)) == (44, 1317)
    assert families == {"A": 16, "B": 1179, "C": 24, "D": 77, "E": 16, "F": 5}
    for record in records:
        assert record["source_url"].startswith("https://cdsco.gov.in/")
        assert re.fullmatch(r"[0-9a-f]{64}", record["source_sha256"])
        assert record["page"] >= 1 and record["row_index"] >= 1
        assert record["extraction_method"] == "rule"
    assert sum(1 for record in records if record["warnings"]) == 2  # the two 2018 two-part packs
