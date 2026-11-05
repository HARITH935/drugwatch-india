"""Jan Aushadhi adapter, against a fake API on localhost (made-up token and products)."""

import json

import pytest

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.sources.jan_aushadhi import (
    PRODUCTS_PATH,
    TOKEN_PATH,
    JanAushadhi,
)

# Made up, JWT-shaped: three base64url parts ("header.payload.signature").
FAKE_TOKEN = "aGVhZGVy.cGF5bG9hZA.c2lnbmF0dXJl"  # noqa: S105 (test value, not a secret)


def token_response(token=FAKE_TOKEN) -> bytes:
    return json.dumps({"responseBody": token, "message": "ok", "responseCode": 200}).encode()


def product(code: int, status: int = 1) -> dict:
    return {
        "productId": code,
        "genericName": f"Test Tablet {code} mg",
        "groupName": "Test Group",
        "drugCode": code,
        "unitSize": "10's",
        "mrp": 12.5,
        "status": status,
        "serialNo": code,
    }


def product_list(*products: dict, total: int | None = None) -> bytes:
    body = {
        "newProductResponsesList": list(products),
        "totalElement": len(products) if total is None else total,
    }
    return json.dumps({"responseBody": body, "message": "ok", "responseCode": 200}).encode()


@pytest.fixture
def jan(http_server, fake_clock, raw_store) -> JanAushadhi:
    fetcher = PoliteFetcher(clock=fake_clock.time, sleep=fake_clock.sleep)
    return JanAushadhi(fetcher, raw_store, api_url=http_server.base_url)


def serve(http_server, products: bytes, token: bytes | None = None):
    http_server.scripts[TOKEN_PATH] = [(200, token or token_response())]
    http_server.scripts[PRODUCTS_PATH] = [(200, products)]


def test_stores_a_monthly_snapshot_using_the_guest_token(jan, http_server):
    body = product_list(product(1), product(2), product(3, status=0))
    serve(http_server, body)

    result = jan.download(month="2026-11")

    assert (result.outcome, result.rows, result.active) == ("stored", 3, 2)
    assert result.key.startswith("jan-aushadhi/products/2026-11/")
    assert jan.store.s3.objects[result.key] == body
    token_request, products_request = http_server.requests
    assert products_request["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert json.loads(http_server.bodies[0])["pageSize"] == 1_000_000
    sidecar = json.loads(jan.store.s3.objects[result.key + ".meta.json"])
    assert (sidecar["snapshot_month"], sidecar["row_count"]) == ("2026-11", 3)


def test_the_token_is_never_stored(jan, http_server):
    serve(http_server, product_list(product(1)))

    jan.download(month="2026-11")

    for stored in jan.store.s3.objects.values():
        assert FAKE_TOKEN.encode() not in stored


def test_a_month_already_stored_is_skipped_without_requests(jan, http_server):
    serve(http_server, product_list(product(1)))
    jan.download(month="2026-11")

    again = jan.download(month="2026-11")

    assert again.outcome == "skipped"
    assert len(http_server.requests) == 2  # only the first run's token + list


def test_refresh_with_unchanged_list_stores_nothing_new(jan, http_server):
    serve(http_server, product_list(product(1)))
    jan.download(month="2026-11")
    writes = len(jan.store.s3.puts)

    again = jan.download(month="2026-11", refresh=True)

    assert again.outcome == "unchanged"
    assert len(jan.store.s3.puts) == writes


@pytest.mark.parametrize(
    "token",
    [
        json.dumps({"responseBody": None, "message": "error"}).encode(),
        json.dumps({"responseBody": "not a jwt"}).encode(),
        json.dumps(
            {"responseBody": "a.b.c\r\nX-Injected: 1"}
        ).encode(),  # must never reach a header
        b"<!DOCTYPE html><html>app homepage</html>",
    ],
)
def test_a_bad_token_stops_before_the_product_request(jan, http_server, token):
    serve(http_server, product_list(product(1)), token=token)

    with pytest.raises(UnexpectedResponseError, match="guest token|not JSON"):
        jan.download(month="2026-11")

    assert len(http_server.requests) == 1  # the product list was never requested


@pytest.mark.parametrize(
    ("products", "message"),
    [
        (b"<!DOCTYPE html><html>app homepage</html>", "not JSON"),
        (json.dumps({"responseBody": {}}).encode(), "no newProductResponsesList"),
        (product_list(), "empty"),
        (product_list(product(1), product(2), total=2500), "totalElement is 2500"),
        (product_list({"drugCode": 1, "mrp": 9.0}), "missing"),
    ],
)
def test_an_unexpected_product_list_stores_nothing(jan, http_server, products, message):
    serve(http_server, products)

    with pytest.raises(UnexpectedResponseError, match=message):
        jan.download(month="2026-11")

    assert jan.store.s3.objects == {}
