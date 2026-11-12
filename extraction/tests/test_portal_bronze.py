"""portal_bronze.py: made-up portal responses (cp1252 bytes), sidecars, the newest-version rule."""

import hashlib
import json
import os

import pytest

from drugwatch_extraction.bronze import BUCKET, from_parquet, to_parquet
from drugwatch_extraction.portal_bronze import (
    PORTAL_SCHEMA,
    PREFIX,
    PortalBronzeError,
    bronze_key,
    newest_per_month,
    portal_records,
    portal_table,
)
from drugwatch_ingestion.store import META_SUFFIX, RawStore

NSQ_ROW = {
    "str_product_name": "Test Tablets IP 500 mg",
    "str_brand_name": "Testol® 500",  # ® is byte 0xAE in cp1252: not valid UTF-8
    "str_batch_no": "TB1201",
    "dt_manufacturing_date": "Feb-2026",
    "dt_expiry_date": None,  # some rows have no expiry date
    "str_manufactured_by": "Test Pharma Pvt. Ltd., Plot 7, Baddi",
    "str_nsq_result": "Dissolution",
    "str_reporting_source": "State lab",
    "str_reported_by_lab_or_state": "LUCKNOW, Uttar Pradesh",
    "dt_reporting_month_year": "SEP-2026",
}


def response(*rows, **extra) -> bytes:
    table = {"iTotalRecords": len(rows), "iTotalDisplayRecords": len(rows), "aaData": list(rows)}
    return json.dumps(table | extra, ensure_ascii=False).encode("cp1252")


def sidecar_for(data: bytes, **overrides) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    if "row_count" not in overrides:  # decode only when needed: some tests pass invalid bytes
        overrides["row_count"] = json.loads(data.decode("cp1252"))["iTotalRecords"]
    return {
        "key": f"cdsco-portal/nsq/2026-09/{sha}.json",
        "sha256": sha,
        "dataset": "nsq",
        "alert_month": "2026-09",
        "encoding": "cp1252",
        "request": {
            "final_url": "https://cdscoonline.gov.in/CDSCO/filteredNsqDrugTable?month=Sep-2026",
            "fetched_at": "2026-11-05T10:00:00+00:00",
        },  # fmt: skip
    } | overrides


def test_every_row_becomes_a_record_with_shared_names_and_provenance():
    data = response(NSQ_ROW, NSQ_ROW | {"str_batch_no": "TB1202"})

    records = portal_records(data, sidecar_for(data))

    first = records[0]
    assert (first["generic_name"], first["brand_name"]) == ("Test Tablets IP 500 mg", "Testol® 500")
    assert (first["batch_no"], first["mfg_date"], first["expiry_date"]) == (
        "TB1201",
        "Feb-2026",
        None,
    )
    assert (first["failure_reason"], first["reported_by"]) == (
        "Dissolution",
        "LUCKNOW, Uttar Pradesh",
    )
    assert (first["extraction_method"], first["row_index"], records[1]["row_index"]) == (
        "api",
        1,
        2,
    )
    assert first["source_url"].endswith("month=Sep-2026")
    assert first["source_key"].startswith("cdsco-portal/nsq/2026-09/")


def test_a_field_the_portal_adds_later_is_kept_in_extra_fields():
    data = response(NSQ_ROW | {"str_new_field": "X", "num_count": 3})

    record = portal_records(data, sidecar_for(data))[0]

    assert record["extra_fields"] == {"str_new_field": "X", "num_count": "3"}


def test_the_parquet_round_trip_keeps_one_schema_and_nulls():
    data = response(NSQ_ROW)

    table = from_parquet(to_parquet(portal_table(portal_records(data, sidecar_for(data)))))

    assert table.schema.equals(PORTAL_SCHEMA)
    row = table.to_pylist()[0]
    assert row["expiry_date"] is None and row["product_name"] is None  # NSQ rows have no full cell
    assert row["brand_name"] == "Testol® 500"  # decoded from cp1252, not mangled


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"sha256": "0" * 64}, "SHA-256"),  # the bytes aren't the ones the sidecar describes
        ({"row_count": 5}, "sidecar says 5"),  # rows lost or added since download
    ],
)
def test_bytes_that_dont_match_their_sidecar_are_refused(change, message):
    data = response(NSQ_ROW)

    with pytest.raises(PortalBronzeError, match=message):
        portal_records(data, sidecar_for(data, **change))


def test_bytes_that_arent_cp1252_are_refused():
    data = b'{"aaData": ["\x81"]}'  # 0x81 is one of the five bytes cp1252 doesn't define

    with pytest.raises(PortalBronzeError, match="not a portal table"):
        portal_records(data, sidecar_for(data, row_count=None))


def test_only_the_newest_response_of_a_month_is_used():
    def side(key, month, fetched):
        return {"key": key, "dataset": "nsq", "alert_month": month,
                "request": {"fetched_at": fetched}}  # fmt: skip

    chosen = newest_per_month(
        [
            side("a", "2026-09", "2026-10-01T00:00:00+00:00"),
            side("b", "2026-09", "2026-11-05T00:00:00+00:00"),  # re-downloaded later
            side("c", "2026-08", "2026-10-01T00:00:00+00:00"),
        ]
    )

    assert [s["key"] for s in chosen] == ["c", "b"]


def test_bronze_key_sits_next_to_the_raw_key():
    assert bronze_key("cdsco-portal/nsq/2026-09/abc.json") == "cdsco-portal/nsq/2026-09/abc.parquet"
    with pytest.raises(ValueError):
        bronze_key("cdsco-portal/nsq/2026-09/abc.json" + META_SUFFIX)


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_whole_portal_archive_converts():
    s3 = RawStore.from_env().s3
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket="raw", Prefix=PREFIX)
    keys = [
        o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(META_SUFFIX)
    ]
    sidecars = [json.loads(s3.get_object(Bucket="raw", Key=k)["Body"].read()) for k in keys]
    rows = {"nsq": 0, "spurious": 0}
    for sidecar in newest_per_month(sidecars):
        data = s3.get_object(Bucket="raw", Key=sidecar["key"])["Body"].read()
        table = from_parquet(to_parquet(portal_table(portal_records(data, sidecar))))
        assert table.schema.equals(PORTAL_SCHEMA)
        rows[sidecar["dataset"]] += table.num_rows

    assert rows == {"nsq": 6956, "spurious": 49}
    assert BUCKET == "bronze"
