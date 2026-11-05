"""CDSCO portal adapter, against a fake portal on localhost serving made-up rows.

Real CDSCO rows are never committed to this public repo: that would be republishing before
permission (ADR 0003). The made-up rows copy the real field names and the cp1252 encoding.
"""

import json

import pytest

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.sources.cdsco_portal import REQUIRED_FIELDS, CdscoPortal

NSQ_PATH = "/CDSCO/filteredNsqDrugTable"


def month_table(month="SEP-2026", rows=2, tab="nsq", **overrides) -> bytes:
    """A made-up month table, encoded like the real portal: cp1252, so ® is the byte 0xAE."""
    row = {field: f"test {field}" for field in REQUIRED_FIELDS[tab]}
    row["str_brand_name"] = "Testbrand® 500"
    row["dt_reporting_month_year"] = month
    table = {"iTotalDisplayRecords": rows, "iTotalRecords": rows, "aaData": [row] * rows}
    table.update(overrides)
    return json.dumps(table, ensure_ascii=False).encode("cp1252")


@pytest.fixture
def portal(http_server, fake_clock, raw_store) -> CdscoPortal:
    fetcher = PoliteFetcher(clock=fake_clock.time, sleep=fake_clock.sleep)
    return CdscoPortal(fetcher, raw_store, base_url=http_server.base_url)


def test_stores_the_exact_bytes_with_metadata(portal, http_server):
    body = month_table(rows=3)
    http_server.scripts[NSQ_PATH] = [(200, body)]

    result = portal.download_month("nsq", "2026-09")

    assert (result.outcome, result.rows) == ("stored", 3)
    assert result.key.startswith("cdsco-portal/nsq/2026-09/")
    stored = portal.store.s3.objects[result.key]
    assert stored == body and b"\xae" in stored  # byte-for-byte, still cp1252
    sidecar = json.loads(portal.store.s3.objects[result.key + ".meta.json"])
    assert sidecar["alert_month"] == "2026-09"
    assert sidecar["row_count"] == 3
    assert sidecar["encoding"] == "cp1252"
    assert sidecar["request"]["url"].endswith("?month=Sep-2026&source=All&tab=nsq")


def test_skips_a_stored_month_without_any_request(portal, http_server):
    http_server.scripts[NSQ_PATH] = [(200, month_table())]
    portal.download_month("nsq", "2026-09")

    again = portal.download_month("nsq", "2026-9")  # also normalises the month

    assert (again.outcome, again.month) == ("skipped", "2026-09")
    assert len(http_server.requests) == 1


def test_refresh_refetches_but_never_restores_the_same_bytes(portal, http_server):
    http_server.scripts[NSQ_PATH] = [(200, month_table())]
    portal.download_month("nsq", "2026-09")

    again = portal.download_month("nsq", "2026-09", refresh=True)

    assert again.outcome == "unchanged"
    assert len(http_server.requests) == 2


def test_late_reports_become_a_new_version(portal, http_server):
    http_server.scripts[NSQ_PATH] = [(200, month_table(rows=2)), (200, month_table(rows=5))]
    first = portal.download_month("nsq", "2026-09")

    later = portal.download_month("nsq", "2026-09", refresh=True)

    assert (later.outcome, later.rows) == ("stored", 5)
    assert later.key != first.key
    assert first.key in portal.store.s3.objects  # the old version is kept


def test_an_empty_month_is_stored_too(portal, http_server):
    http_server.scripts[NSQ_PATH] = [(200, month_table(rows=0))]

    result = portal.download_month("nsq", "2019-02")

    assert (result.outcome, result.rows) == ("stored", 0)


def test_spurious_uses_its_own_endpoint_and_fields(portal, http_server):
    http_server.scripts["/CDSCO/filteredSpuriousDrugTable"] = [
        (200, month_table(tab="spurious", month="MAR-2025"))
    ]

    result = portal.download_month("spurious", "2025-03")

    assert result.key.startswith("cdsco-portal/spurious/2025-03/")
    assert "tab=spurious" in http_server.requests[0]["path"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<!DOCTYPE html><html>maintenance</html>", "not JSON"),
        (json.dumps({"rows": []}).encode(), "no aaData list"),
        (month_table(rows=2, iTotalRecords=500), "iTotalRecords is 500"),
        (month_table(month="AUG-2026"), "month is 'AUG-2026'"),
        (
            json.dumps({"iTotalRecords": 1, "aaData": [{"str_batch_no": "B1"}]}).encode(),
            "missing",
        ),
    ],
)
def test_unexpected_shapes_stop_the_run_and_store_nothing(portal, http_server, body, message):
    http_server.scripts[NSQ_PATH] = [(200, body)]

    with pytest.raises(UnexpectedResponseError, match=message):
        portal.download_month("nsq", "2026-09")

    assert portal.store.s3.objects == {}


def test_available_months_come_from_the_portal_menus(portal, http_server):
    http_server.scripts["/CDSCO/reportingYears"] = [(200, b"[2026, 2025]")]
    http_server.scripts["/CDSCO/publicReportingMonths"] = [
        (200, json.dumps(["Nov", "Dec"]).encode()),  # 2025 (years are asked oldest first)
        (200, json.dumps(["Jan", "Feb", "Mar"]).encode()),  # 2026
    ]

    months = portal.available_months("nsq")

    assert months == ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
    assert "year=2025&tab=nsq" in http_server.requests[1]["path"]


def test_available_months_rejects_unknown_month_names(portal, http_server):
    http_server.scripts["/CDSCO/reportingYears"] = [(200, b"[2026]")]
    http_server.scripts["/CDSCO/publicReportingMonths"] = [(200, b'["Sept"]')]

    with pytest.raises(UnexpectedResponseError, match="Sept"):
        portal.available_months("nsq")


@pytest.mark.parametrize(
    ("tab", "month"), [("nsq", "Sep-2026"), ("nsq", "2026-13"), ("x", "2026-09")]
)
def test_rejects_bad_arguments(portal, tab, month):
    with pytest.raises(ValueError):
        portal.download_month(tab, month)
