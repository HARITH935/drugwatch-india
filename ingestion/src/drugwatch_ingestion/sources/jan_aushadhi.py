"""Jan Aushadhi adapter (janaushadhi.gov.in): the Product & MRP list (docs/data-sources.md §3).

The public "Product & MRP List" page is a JavaScript app. A visitor's browser makes two requests,
and so do we (ADR 0003: only what a logged-out browser does by itself):
1. GET  :8443/auth/generateGuestToken  -> a short-lived guest token (a JWT) that the site
                                         hands to every anonymous visitor;
2. POST :8443/api/v1/website/getAllProductForWeb  -> every product, in one response, sent
                                         with "Authorization: Bearer <token>".

The token is a credential: it's checked, used once and never stored, printed or logged.

The list isn't monthly, so each run stores a SNAPSHOT under the month it was collected:
raw/jan-aushadhi/products/<YYYY-MM>/. A second run in the same month is skipped (no requests).

Run (from ingestion/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_ingestion.sources.jan_aushadhi
"""

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.store import RawStore

API_URL = "https://janaushadhi.gov.in:8443"
TOKEN_PATH = "/auth/generateGuestToken"  # noqa: S105 (a URL path, not a password)
PRODUCTS_PATH = "/api/v1/website/getAllProductForWeb"
SOURCE = "jan-aushadhi"

# The same body the site's own "export" sends: everything in one page, sorted by drug code.
REQUEST_BODY = {
    "pageIndex": 0,
    "pageSize": 1_000_000,
    "searchText": "",
    "columnName": "drug_code",
    "orderBy": "asc",
}
REQUIRED_FIELDS = (
    frozenset(  # seen in the real response, 2026-11-05 (serialNo is just a row number)
        {"productId", "genericName", "groupName", "drugCode", "unitSize", "mrp", "status"}
    )
)
# A JWT is three base64url parts joined by dots. Checked before the token goes into a header.
_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")


@dataclass(frozen=True)
class SnapshotResult:
    month: str  # YYYY-MM the snapshot was collected in
    outcome: str  # "stored" / "unchanged" / "skipped" (already have this month's: no requests)
    rows: int | None = None
    active: int | None = None  # rows with status == 1: what the public page shows
    key: str | None = None


class JanAushadhi:
    def __init__(self, fetcher: PoliteFetcher, store: RawStore, api_url: str = API_URL):
        self.fetcher = fetcher
        self.store = store
        self.api_url = api_url  # tests point this at a local fake API

    def download(self, *, month: str | None = None, refresh: bool = False) -> SnapshotResult:
        """Store this month's snapshot of the product list, unless it's already stored."""
        month = month or datetime.now(UTC).strftime("%Y-%m")
        prefix = f"{SOURCE}/products/{month}"
        if not refresh and self.store.has_item(prefix):
            return SnapshotResult(month, "skipped")

        token = self._guest_token()
        result = self.fetcher.fetch(
            self.api_url + PRODUCTS_PATH,
            http_method="POST",
            json=REQUEST_BODY,
            headers={"Authorization": f"Bearer {token}"},  # sent, never stored (see provenance())
        )
        rows, active = check_product_list(result.content)
        stored = self.store.put(
            prefix,
            result.content,
            "json",
            {
                "source": SOURCE,
                "method": "auto",
                "dataset": "products",
                "snapshot_month": month,
                "row_count": rows,
                "active_count": active,
                "request_body": REQUEST_BODY,  # the POST body: no secrets in it
                "request": result.provenance(),
            },
        )
        outcome = "stored" if stored.created else "unchanged"
        return SnapshotResult(month, outcome, rows, active, stored.key)

    def _guest_token(self) -> str:
        result = self.fetcher.fetch(self.api_url + TOKEN_PATH)
        body = _parse_json(result.content, TOKEN_PATH)
        token = body.get("responseBody") if isinstance(body, dict) else None
        if not isinstance(token, str) or not _JWT.fullmatch(token):
            # Never put the response itself in the message: it may contain a token.
            fields = sorted(body) if isinstance(body, dict) else type(body).__name__
            raise UnexpectedResponseError(
                f"{TOKEN_PATH}: no guest token in the response ({fields})"
            )
        return token


def check_product_list(content: bytes) -> tuple[int, int]:
    """Check the product list is complete and shaped as expected; return (rows, active rows)."""
    data = _parse_json(content, PRODUCTS_PATH)
    body = data.get("responseBody") if isinstance(data, dict) else None
    products = body.get("newProductResponsesList") if isinstance(body, dict) else None
    if not isinstance(products, list):
        raise UnexpectedResponseError(f"{PRODUCTS_PATH}: no newProductResponsesList")
    if not products:
        raise UnexpectedResponseError(f"{PRODUCTS_PATH}: the product list is empty")
    if body.get("totalElement") != len(products):  # one page must hold the whole list
        raise UnexpectedResponseError(
            f"{PRODUCTS_PATH}: totalElement is {body.get('totalElement')!r}, got {len(products)}"
        )
    for index, product in enumerate(products):
        if not isinstance(product, dict):
            raise UnexpectedResponseError(f"{PRODUCTS_PATH} row {index}: not an object")
        missing = REQUIRED_FIELDS - product.keys()
        if missing:
            raise UnexpectedResponseError(f"{PRODUCTS_PATH} row {index}: missing {sorted(missing)}")
    return len(products), sum(1 for product in products if product["status"] == 1)


def _parse_json(content: bytes, what: str) -> Any:
    try:
        return json.loads(content)
    except ValueError:
        # e.g. the app's HTML homepage, which this site returns (with HTTP 200) for unknown paths
        raise UnexpectedResponseError(f"{what}: not JSON (starts {content[:40]!r})") from None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Store this month's Jan Aushadhi product list.")
    parser.add_argument("--refresh", action="store_true", help="re-download this month's snapshot")
    args = parser.parse_args(argv)

    result = JanAushadhi(PoliteFetcher(), RawStore.from_env()).download(refresh=args.refresh)
    detail = (
        f", {result.rows} products ({result.active} active) -> raw/{result.key}"
        if result.key
        else ""
    )
    print(f"jan-aushadhi products {result.month}: {result.outcome}{detail}")


if __name__ == "__main__":
    main()
