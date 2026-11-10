"""Write extracted records to the bronze bucket as Parquet (Phase 2 step 6, ADR 0007).

    raw/cdsco-pdf/<dataset>/<month>/<file_id>/<sha256>.pdf
    -> bronze/cdsco-pdf/<dataset>/<month>/<file_id>/<sha256>.parquet     (one file per source PDF)

The file name stays the source PDF's SHA-256, so a bronze file points at the exact bytes it came
from, and re-running replaces the file instead of adding a copy.

Every file has the same SCHEMA, whichever layout family the PDF has, so Phase 3's Spark job can read
them all as one table:
- a field the PDF's layout doesn't have is NULL; an empty cell stays "" (kept as extracted);
- a header no vocabulary knows ("other_*" fields) goes into the extra_fields map, not a new column;
- any other unexpected field stops the write (BronzeSchemaError): pyarrow would silently drop it.

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.bronze --all
"""

import argparse
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from drugwatch_extraction.extract import ExtractionResult, extract_pdf, pdf_keys
from drugwatch_ingestion.store import RawStore

BUCKET = "bronze"

# Provenance and confidence (extract.py). nullable=False: pyarrow refuses to WRITE a file with a
# null there, a last check that every record says where it came from.
PROVENANCE = [
    pa.field("source_key", pa.string(), nullable=False),
    pa.field("source_sha256", pa.string(), nullable=False),
    pa.field("source_url", pa.string()),
    pa.field("source_dataset", pa.string()),
    pa.field("alert_month", pa.string()),  # "2025-06"; null for the 2017-2023 bulk vaccine file
    pa.field("file_id", pa.string()),
    pa.field("listing_title", pa.string()),
    pa.field("family", pa.string(), nullable=False),
    pa.field("page", pa.int32(), nullable=False),
    pa.field("pages", pa.list_(pa.int32()), nullable=False),
    pa.field("row_index", pa.int32(), nullable=False),
    pa.field("section", pa.string()),
    pa.field("extraction_method", pa.string(), nullable=False),
    pa.field("extractor_version", pa.string(), nullable=False),
    pa.field("warnings", pa.list_(pa.string()), nullable=False),
    pa.field("confidence", pa.string(), nullable=False),
    pa.field("confidence_reasons", pa.list_(pa.string()), nullable=False),
]
# Every row field a family parser can produce, as text (test_bronze.py checks this list against the
# family vocabularies).
ROW_FIELDS = (
    "serial_no", "product_name", "batch_no", "batch_details", "mfg_date", "expiry_date",
    "manufacturer", "failure_reason", "reported_by", "drawn_by", "drawn_from", "firm_reply",
    "remarks", "sample_source", "status", "regulatory_action", "report_year", "sales_outlets",
    "manufacturer_response",
)  # fmt: skip
SCHEMA = pa.schema(
    PROVENANCE
    + [pa.field(name, pa.string()) for name in ROW_FIELDS]
    + [pa.field("extra_fields", pa.map_(pa.string(), pa.string()), nullable=False)]
)


class BronzeSchemaError(ValueError):
    """A record has a field the bronze schema doesn't know."""


def bronze_key(source_key: str) -> str:
    if not source_key.endswith(".pdf"):
        raise ValueError(f"not a PDF key: {source_key}")
    return source_key.removesuffix(".pdf") + ".parquet"


def to_table(records: list[dict[str, Any]]) -> pa.Table:
    rows = []
    for record in records:
        extra = {name: value for name, value in record.items() if name.startswith("other_")}
        unexpected = set(record) - set(SCHEMA.names) - set(extra)
        if unexpected:
            raise BronzeSchemaError(f"fields not in the bronze schema: {sorted(unexpected)}")
        row = {name: value for name, value in record.items() if name not in extra}
        rows.append(row | {"extra_fields": extra})
    return pa.Table.from_pylist(rows, schema=SCHEMA)  # fields a record lacks become null


def to_parquet(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()  # Arrow's own in-memory file
    pq.write_table(table, sink)  # snappy-compressed by default
    return sink.getvalue().to_pybytes()


def from_parquet(data: bytes) -> pa.Table:
    """Read a Parquet file held in memory, on this thread only.

    Bronze files are a few KB, so threads gain nothing, and this path starts no Arrow worker
    threads. pq.read_table() or a Python file object (io.BytesIO) start Arrow's thread pools, and
    on macOS the process then sometimes hung at exit, waiting for a pool worker (extraction report
    §2.10).
    """
    return pq.ParquetFile(pa.BufferReader(data)).read(use_threads=False)


def write_bronze(s3: Any, result: ExtractionResult) -> str:
    """Write one PDF's records to bronze/; returns the key written."""
    key = bronze_key(result.key)
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=to_parquet(to_table(result.records)),
        ContentType="application/vnd.apache.parquet",
    )
    return key


def read_bronze(s3: Any, key: str) -> pa.Table:
    return from_parquet(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Extract CDSCO PDFs from raw/ into bronze/.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--key", help="one PDF's raw/ key")
    which.add_argument("--all", action="store_true", help="every PDF under cdsco-pdf/")
    args = parser.parse_args(argv)

    s3 = RawStore.from_env().s3
    keys = pdf_keys(s3) if args.all else [args.key]
    written, rows, problems = [], 0, []
    for key in keys:
        result = extract_pdf(s3, key)
        if result.problem:
            problems.append(f"{key}: {result.problem}")  # nothing written for this PDF
            continue
        written.append(write_bronze(s3, result))
        rows += len(result.records)
    print(f"wrote {len(written)} Parquet files, {rows} rows, to {BUCKET}/")

    # Read every file back from RustFS: the check is what Phase 3 will actually see.
    tables = [read_bronze(s3, key) for key in written]
    same_schema = all(table.schema.equals(SCHEMA) for table in tables)
    read_rows = sum(table.num_rows for table in tables)
    print(f"read back: {len(tables)} files, {read_rows} rows, schema identical: {same_schema}")
    if read_rows != rows or not same_schema:
        problems.append("read-back doesn't match what was written")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)


if __name__ == "__main__":
    main()
