"""CDSCO portal JSON -> bronze Parquet (Phase 3 step 0; ADR 0004, ADR 0007).

    raw/cdsco-portal/<tab>/<YYYY-MM>/<sha256>.json
    -> bronze/cdsco-portal/<tab>/<YYYY-MM>/<sha256>.parquet     (one file per month)

The portal is CDSCO's primary source from 2019 (ADR 0004): 6,956 NSQ + 49 spurious rows. Each
month's response is decoded as Windows-1252 (the portal's real encoding; strict, so a byte that
isn't valid cp1252 stops the run) and every row becomes a record. Values stay exactly as the
portal gives them (bronze rule), including its quirks: lost leading zeros, "?" for dashes
(data-sources.md §1b).

Field names follow the PDF records where the meaning is the same (FIELD_NAMES). Two differences:
- NSQ rows: `str_product_name` is only the GENERIC name (the brand is separate), so it becomes
  `generic_name`; the PDFs' `product_name` is the whole printed cell (brand included).
- Spurious rows: `product_name_from_dtl` is the whole product cell, as in the PDFs: `product_name`.
  CAUTION (as for PDF families C and F): `manufacturer` is the name on the FAKE pack, usually
  "Under Investigation", sometimes the genuine company whose brand was copied. Never count it
  against that company; `spurious_manufacturer_name` is the faker, once identified.
A field the portal adds in future goes into `extra_fields` (kept, not lost, not a new column).

Provenance: the raw key and SHA-256, the request URL, when it was fetched, the row's position in
the response, and `extraction_method = "api"` (the portal sends data, nothing is read off a page:
there is no page number). If a month was downloaded more than once (state labs report late), only
the newest response is in bronze; older bronze files for that month are removed (raw/ keeps all).

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.portal_bronze --all
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from typing import Any

import pyarrow as pa

from drugwatch_extraction import __version__
from drugwatch_extraction.bronze import BUCKET, read_bronze, to_parquet
from drugwatch_ingestion.store import META_SUFFIX, RawStore

PREFIX = "cdsco-portal/"
FIELD_NAMES = {  # portal field -> bronze field
    "str_product_name": "generic_name",  # NSQ: the generic name only; the brand is str_brand_name
    "product_name_from_dtl": "product_name",  # spurious: the whole product cell, as in the PDFs
    "str_brand_name": "brand_name",
    "str_batch_no": "batch_no",
    "dt_manufacturing_date": "mfg_date",  # "Feb-2026": month precision, as printed
    "dt_expiry_date": "expiry_date",
    "str_manufactured_by": "manufacturer",  # name and full address in one string
    "str_nsq_result": "failure_reason",
    "str_reporting_source": "reporting_source",  # e.g. "CDSCO lab", "State lab"
    "str_reported_by_lab_or_state": "reported_by",  # the lab or state that reported it
    "dt_reporting_month_year": "reporting_month",  # "SEP-2026", as sent
    "str_nsq_remarks": "remarks",
    "str_firm_reply": "firm_reply",
    "str_spurious_manufacturer_name": "spurious_manufacturer_name",  # the faker, once identified
    "str_spurious_manufactured_by": "spurious_manufactured_by",
}
PORTAL_SCHEMA = pa.schema(
    [
        pa.field("source_key", pa.string(), nullable=False),
        pa.field("source_sha256", pa.string(), nullable=False),
        pa.field("source_url", pa.string()),  # the request, with its month parameter
        pa.field("source_dataset", pa.string(), nullable=False),  # "nsq" or "spurious"
        pa.field("alert_month", pa.string(), nullable=False),  # "2026-09"
        pa.field("fetched_at", pa.string()),  # when the response was downloaded (UTC)
        pa.field("row_index", pa.int32(), nullable=False),  # 1-based position in the response
        pa.field("extraction_method", pa.string(), nullable=False),  # "api"
        pa.field("extractor_version", pa.string(), nullable=False),
    ]
    + [pa.field(name, pa.string()) for name in FIELD_NAMES.values()]
    + [pa.field("extra_fields", pa.map_(pa.string(), pa.string()), nullable=False)]
)


class PortalBronzeError(ValueError):
    """The raw bytes don't match their sidecar, or the response isn't what was stored."""


def portal_records(data: bytes, sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    """The pure core: one raw response and its sidecar in, one record per row out."""
    if _sha256(data) != sidecar["sha256"]:
        raise PortalBronzeError(f"{sidecar['key']}: bytes don't match the sidecar's SHA-256")
    try:
        rows = json.loads(data.decode(sidecar.get("encoding", "cp1252")))["aaData"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise PortalBronzeError(f"{sidecar['key']}: not a portal table ({error})") from None
    if sidecar.get("row_count") is not None and len(rows) != sidecar["row_count"]:
        raise PortalBronzeError(
            f"{sidecar['key']}: {len(rows)} rows, sidecar says {sidecar['row_count']}"
        )
    provenance = {
        "source_key": sidecar["key"],
        "source_sha256": sidecar["sha256"],
        "source_url": sidecar.get("request", {}).get("final_url"),
        "source_dataset": sidecar["dataset"],
        "alert_month": sidecar["alert_month"],
        "fetched_at": sidecar.get("request", {}).get("fetched_at"),
        "extraction_method": "api",
        "extractor_version": __version__,
    }
    records = []
    for index, row in enumerate(rows, start=1):
        record = {**provenance, "row_index": index, "extra_fields": {}}
        for field, value in row.items():
            if field in FIELD_NAMES:
                record[FIELD_NAMES[field]] = _text(value)
            elif (text := _text(value)) is not None:
                record["extra_fields"][field] = text  # a field the portal added later
        records.append(record)
    return records


def portal_table(records: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(records, schema=PORTAL_SCHEMA)  # fields a row lacks become null


def bronze_key(raw_key: str) -> str:
    is_response = raw_key.endswith(".json") and not raw_key.endswith(META_SUFFIX)  # not a sidecar
    if not (raw_key.startswith(PREFIX) and is_response):
        raise ValueError(f"not a portal response key: {raw_key}")
    return raw_key.removesuffix(".json") + ".parquet"


def newest_per_month(sidecars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each (tab, month), the most recently fetched response (state labs report late)."""
    months: dict[tuple, list[dict]] = defaultdict(list)
    for sidecar in sidecars:
        months[(sidecar["dataset"], sidecar["alert_month"])].append(sidecar)
    return [
        max(versions, key=lambda s: (s.get("request", {}).get("fetched_at") or "", s["key"]))
        for _, versions in sorted(months.items())
    ]


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)  # a number or list, kept as its JSON text


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _keys(s3: Any, bucket: str, prefix: str) -> list[str]:
    return sorted(
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Turn the CDSCO portal JSON in raw/ into bronze/.")
    parser.add_argument("--all", action="store_true", required=True)
    parser.parse_args(argv)

    s3 = RawStore.from_env().s3
    sidecars = [
        json.loads(s3.get_object(Bucket="raw", Key=key)["Body"].read())
        for key in _keys(s3, "raw", PREFIX)
        if key.endswith(META_SUFFIX)
    ]
    written, rows, removed = [], 0, []
    for sidecar in newest_per_month(sidecars):
        data = s3.get_object(Bucket="raw", Key=sidecar["key"])["Body"].read()
        records = portal_records(data, sidecar)
        key = bronze_key(sidecar["key"])
        s3.put_object(Bucket=BUCKET, Key=key, Body=to_parquet(portal_table(records)),
                      ContentType="application/vnd.apache.parquet")  # fmt: skip
        written.append(key)
        rows += len(records)
        month_prefix = key.rsplit("/", 1)[0] + "/"
        for old in _keys(s3, BUCKET, month_prefix):  # an older response's bronze file
            if old != key:
                s3.delete_object(Bucket=BUCKET, Key=old)
                removed.append(old)
    print(f"wrote {len(written)} Parquet files, {rows} rows, to {BUCKET}/{PREFIX}")
    if removed:
        print(f"removed {len(removed)} bronze file(s) of older responses")

    tables = [read_bronze(s3, key) for key in written]
    same = all(table.schema.equals(PORTAL_SCHEMA) for table in tables)
    read_rows = sum(table.num_rows for table in tables)
    print(f"read back: {len(tables)} files, {read_rows} rows, schema identical: {same}")
    if read_rows != rows or not same:
        sys.exit("read-back doesn't match what was written")


if __name__ == "__main__":
    main()
