"""Family A parser: vaccine lists with a title and a section row above the header (made-up rows)."""

import json
import os
import re

import pytest

from drugwatch_extraction.classify import classify_pdf
from drugwatch_extraction.family_a import parse_family_a
from drugwatch_ingestion.store import RawStore

HEADER = [
    "S.No.",
    "Vaccine Name",
    "Batch No.",
    "Manufacturing Date",
    "Expiry Date",
    "Manufactured By",
    "NSQ Result",
    "Reported by",
]


def full_width(text):
    return [text, "", "", "", "", "", "", ""]


def test_title_and_section_rows_sit_above_the_header(table_pdf):
    pdf = table_pdf(
        [
            full_width("NSQ ALERT FOR THE MONTH OF MAR-2022."),
            full_width("A. Central Laboratories"),
            HEADER,
            ["3", "Test Vaccine", "V001", "Apr'22", "Mar'25", "M/s Test", "Assay", "CDL"],
        ]
    )

    result = parse_family_a(pdf)

    [row] = result.rows
    assert row.section == "A. Central Laboratories"  # the nearest section row above it
    assert row.fields["product_name"] == "Test Vaccine"
    assert result.first_serial == 3  # a list may start above 1 (CDSCO's Mar 2022 does)


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_real_vaccine_lists():
    s3 = RawStore.from_env().s3
    listing = s3.list_objects_v2(Bucket="raw", Prefix="cdsco-pdf/central-nsq/")["Contents"]
    files = rows = matched = checked = 0
    for key in sorted(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf")):
        data = s3.get_object(Bucket="raw", Key=key)["Body"].read()
        if classify_pdf(data).family != "A":
            continue
        result = parse_family_a(data)
        assert (result.serial_gaps, result.unknown_headers, result.skipped) == ([], [], []), key
        files += 1
        rows += len(result.rows)
        month = key.split("/")[2]
        if month < "2019":
            continue  # the portal starts in Jan 2019
        portal_key = next(
            obj["Key"]
            for obj in s3.list_objects_v2(Bucket="raw", Prefix=f"cdsco-portal/nsq/{month}/")[
                "Contents"
            ]
            if obj["Key"].endswith(".json") and not obj["Key"].endswith(".meta.json")
        )
        portal = json.loads(
            s3.get_object(Bucket="raw", Key=portal_key)["Body"].read().decode("cp1252")
        )
        portal_batches = {re.sub(r"\s+", "", p["str_batch_no"]).upper() for p in portal["aaData"]}
        for row in result.rows:
            batch = re.sub(r"\s+", "", row.fields["batch_no"]).upper()
            if batch.strip("-"):  # "--" means no batch number was printed: nothing to match
                checked += 1
                matched += batch in portal_batches

    assert (files, rows) == (11, 16)
    assert (matched, checked) == (7, 7)  # every real batch from 2019 on (one more row prints "--")
