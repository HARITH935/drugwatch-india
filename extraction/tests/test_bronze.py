"""bronze.py: one schema for every family, Parquet round trip, one file per source PDF."""

import hashlib
import os
import subprocess
from collections import Counter

import pytest

from drugwatch_extraction import family_a, family_b, family_c, family_d, family_e, family_f
from drugwatch_extraction.bronze import (
    ROW_FIELDS,
    SCHEMA,
    BronzeSchemaError,
    bronze_key,
    from_parquet,
    to_parquet,
    to_table,
    write_bronze,
)
from drugwatch_extraction.extract import extract_pdf, pdf_keys, records_for
from drugwatch_ingestion.store import RawStore

KEY = "cdsco-pdf/central-nsq/2025-06/12927/{sha}.pdf"
B_HEADER = ["S.No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date",
            "Manufactured By", "NSQ Result", "Reported by"]  # fmt: skip


def b_result(table_pdf):
    """Real records from a self-built family-B PDF; row 2 leaves "Reported by" blank."""
    data = table_pdf(
        [
            B_HEADER,
            ["1.", "Test Tablet", "TB1", "01/2025", "12/2026", "M/s. Test", "Assay", "CDL"],
            ["2.", "Test Syrup", "TB2", "01/2025", "12/2026", "M/s. Test", "pH", ""],
        ]
    )
    sha = hashlib.sha256(data).hexdigest()
    sidecar = {
        "key": KEY.format(sha=sha),
        "sha256": sha,
        "dataset": "central-nsq",
        "alert_month": "2025-06",
        "file_id": "12927",
        "listing": {"title": "NSQ ALERT FOR THE MONTH OF June 2025"},
        "request": {"final_url": "https://cdsco.gov.in/opencms/resources/test.pdf"},
    }
    return records_for(data, sidecar)


def round_trip(records):
    return from_parquet(to_parquet(to_table(records)))


def os_thread_count() -> int:
    """Threads of this process, including C++ ones Python's threading module can't see."""
    if os.path.isdir("/proc/self/task"):  # Linux (CI)
        return len(os.listdir("/proc/self/task"))
    ps = ["/bin/ps", "-M", str(os.getpid())]  # macOS: one line per thread, plus a header
    out = subprocess.run(ps, capture_output=True, text=True, check=True).stdout  # noqa: S603
    return len(out.splitlines()) - 1


def test_reading_bronze_starts_no_arrow_worker_threads(table_pdf):
    # Kept first in this file. Arrow's thread pools made the process hang at exit on macOS
    # (extraction report §2.10); from_parquet must never start them.
    data = to_parquet(to_table(b_result(table_pdf).records))
    before = os_thread_count()

    for _ in range(5):
        from_parquet(data)

    assert os_thread_count() == before


def test_the_schema_has_a_column_for_every_field_a_family_can_produce():
    produced = {
        field
        for module in (family_a, family_b, family_c, family_d, family_e, family_f)
        for field, _ in module.VOCABULARY
    }
    produced |= set(family_d.SPLIT_FIELDS) | {"report_year"}  # added after the engine runs

    assert produced == set(ROW_FIELDS)


def test_null_means_no_such_column_and_empty_means_a_blank_cell(table_pdf):
    table = round_trip(b_result(table_pdf).records)

    assert table.schema.equals(SCHEMA)
    rows = table.to_pylist()
    assert [r["batch_no"] for r in rows] == ["TB1", "TB2"]
    assert rows[1]["reported_by"] == ""  # family B has the column; this cell was blank
    assert rows[0]["drawn_by"] is None  # family B's layout has no "Drawn by" column
    assert rows[0]["pages"] == [1] and rows[0]["confidence_reasons"] == []
    assert rows[0]["extra_fields"] == []  # a map with no entries


def test_an_unknown_header_goes_into_extra_fields(table_pdf):
    record = b_result(table_pdf).records[0] | {"other_lab_code": "K-7"}

    row = round_trip([record]).to_pylist()[0]

    assert row["extra_fields"] == [("other_lab_code", "K-7")]


def test_an_unexpected_field_is_refused_not_dropped(table_pdf):
    record = b_result(table_pdf).records[0] | {"batch_number": "TB1"}  # a misspelt field name

    with pytest.raises(BronzeSchemaError, match="batch_number"):
        to_table([record])


def test_a_record_without_provenance_cannot_be_written(table_pdf):
    record = b_result(table_pdf).records[0] | {"source_key": None}

    with pytest.raises(Exception, match="non-nullable"):
        to_parquet(to_table([record]))


def test_one_file_per_source_pdf_next_to_its_raw_key(table_pdf):
    class FakeS3:
        def __init__(self):
            self.puts = []

        def put_object(self, **kwargs):
            self.puts.append(kwargs)

    s3, result = FakeS3(), b_result(table_pdf)

    key = write_bronze(s3, result)

    assert key == result.key.removesuffix(".pdf") + ".parquet"
    assert [(put["Bucket"], put["Key"]) for put in s3.puts] == [("bronze", key)]
    assert from_parquet(s3.puts[0]["Body"]).num_rows == 2
    with pytest.raises(ValueError):
        bronze_key("cdsco-pdf/central-nsq/2025-06/12927/abc.meta.json")


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_whole_archive_round_trips_through_parquet():
    s3 = RawStore.from_env().s3
    rows, confidence = 0, Counter()
    for key in pdf_keys(s3):
        table = round_trip(extract_pdf(s3, key).records)
        assert table.schema.equals(SCHEMA), key
        rows += table.num_rows
        confidence.update(table.column("confidence").to_pylist())

    assert rows == 1317
    assert confidence == {"high": 1214, "low": 103}
