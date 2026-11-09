"""Family E: one table and one year per page (made-up rows, CDSCO's real column names)."""

import os
import re
from collections import Counter

import pytest

from drugwatch_extraction.classify import classify_pdf
from drugwatch_extraction.family_a import parse_family_a
from drugwatch_extraction.family_e import parse_family_e
from drugwatch_ingestion.store import RawStore

HEADER = ["S.No", "Name of Vaccine", "Manufacturer", "Batch No.", "Mfg Date", "Exp Date",
          "Sub-Standard in", "Status"]  # fmt: skip


def title(year):
    return [f"Samples of year {year}", "", "", "", "", "", "", ""]


def row(serial, batch):
    return [serial, "Test Vaccine", "M/s Test", batch, "Apr-15", "Mar-18", "Assay", "NSQ"]


def test_each_row_gets_its_own_pages_year(table_pdf):
    pdf = table_pdf(
        [title(2017), HEADER, row("1", "V1"), row("2", "V2")],
        [title(2018), HEADER, row("1", "V3")],  # serial numbers restart on every page
    )

    result = parse_family_e(pdf)

    assert [r.fields["report_year"] for r in result.rows] == ["2017", "2017", "2018"]
    assert result.rows[2].section == "Samples of year 2018"  # not page 1's title carried over
    assert result.warnings == [] and result.serial_gaps == []


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_real_bulk_file_repeats_the_vaccine_lists():
    s3 = RawStore.from_env().s3
    listing = s3.list_objects_v2(Bucket="raw", Prefix="cdsco-pdf/nsq-bulk/")["Contents"]
    key = next(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf"))

    result = parse_family_e(s3.get_object(Bucket="raw", Key=key)["Body"].read())

    years = Counter(row.fields["report_year"] for row in result.rows)
    assert years == {"2017": 2, "2018": 6, "2019": 2, "2022": 5, "2023": 1}
    assert (result.warnings, result.unknown_headers, result.skipped) == ([], [], [])

    # The same 16 batches as the family-A vaccine lists, with status and regulatory action added:
    # Phase 3 must count each as one finding, not two.
    a_batches = []
    listing = s3.list_objects_v2(Bucket="raw", Prefix="cdsco-pdf/central-nsq/")["Contents"]
    for a_key in sorted(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf")):
        data = s3.get_object(Bucket="raw", Key=a_key)["Body"].read()
        if classify_pdf(data).family == "A":
            a_batches += [row.fields["batch_no"] for row in parse_family_a(data).rows]

    def norm(batches):
        return Counter(re.sub(r"\s+", "", batch).upper() for batch in batches)

    assert norm(row.fields["batch_no"] for row in result.rows) == norm(a_batches)
