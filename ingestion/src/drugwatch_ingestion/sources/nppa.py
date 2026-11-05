"""NPPA adapter (nppa.gov.in): ceiling-price documents (docs/data-sources.md §2).

Four listing pages, two table shapes:
- REFERENCE pages (Compendium of Prices, DPCO 2013 lists, therapeutic-category lists) have a
  "Sr.No. | Document Name | Download" table. A row links either to a PDF or (the 2014 DPCO lists)
  to another NPPA page whose HTML table IS the data. Both are stored as received: .pdf / .html.
- The ORDERS feed ("Sr. No. | Date | Title | Attachment") links one PDF per order, 2026 onwards.

Stored under raw/nppa/<section>/<doc id>/ and raw/nppa/orders/<YYYY-MM>/<doc id>/. The doc id comes
from NPPA's own file or page name, so it's stable. The 2026 Compendium dashboard isn't here: it's a
manual drop (ADR 0003). nppa.gov.in needs the extra intermediate certificate in certs/.

Run (from ingestion/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_ingestion.sources.nppa --list
    uv run --env-file ../.env python -m drugwatch_ingestion.sources.nppa --section compendium --all
"""

import argparse
import html
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.sources.html_tables import parse_tables
from drugwatch_ingestion.store import RawStore

SITE = "https://nppa.gov.in"
SOURCE = "nppa"
REFERENCE_PATHS = {  # section -> page with a "Document Name" table
    "compendium": "/en/compendiumofprice",
    "dpco2013": "/en/dpco2013",
    "category-lists": "/en/therapeuticcategorywiseceilingpricelist",
}
ORDERS_PATH = "/en/view_more?id=4"
ORDERS_HEADERS = ["Sr. No.", "Date", "Title", "Attachment"]
SECTIONS = [*REFERENCE_PATHS, "orders"]


@dataclass(frozen=True)
class NppaDocument:
    section: str  # compendium / dpco2013 / category-lists / orders
    doc_id: str  # from NPPA's file or page name, e.g. "retail-04-11-2026"
    title: str
    url: str
    file_type: str  # "pdf", or "html" for an NPPA page whose table is the data itself
    listing_url: str
    order_date: date | None = None  # orders only
    size_text: str | None = None  # as the listing shows it, e.g. "934KB/PDF/English"

    @property
    def prefix(self) -> str:
        if self.order_date is not None:
            return f"{SOURCE}/orders/{self.order_date:%Y-%m}/{self.doc_id}"
        return f"{SOURCE}/{self.section}/{self.doc_id}"


@dataclass(frozen=True)
class DocumentResult:
    document: NppaDocument
    outcome: str  # "stored" / "unchanged" / "skipped" (already stored: no request made)
    key: str | None = None


def reference_documents(page: str, page_url: str, section: str):
    """Documents linked from a "Document Name" table, and rows skipped (with the reason)."""
    tables = [table for table in parse_tables(page) if "Document Name" in table.headers]
    if not tables:
        raise UnexpectedResponseError(f"{page_url}: no 'Document Name' table")
    documents: list[NppaDocument] = []
    skipped: list[tuple[str, str]] = []
    for row in (row for table in tables for row in table.rows):
        if len(row) == 2:  # e.g. the 2013 DPCO rows: listed, but with no Download cell at all
            skipped.append((row[1][0], "no link on the page"))
            continue
        if len(row) != 3:
            raise UnexpectedResponseError(f"{page_url}: unexpected row {row!r}")
        (_, _), (title, _), (size_text, href) = row
        if href is None:
            skipped.append((title, "no link on the page"))
            continue
        url = urljoin(page_url, html.unescape(href))
        if _is_pdf(url):
            file_type = "pdf"
        elif urlsplit(url).hostname == urlsplit(page_url).hostname:
            file_type = "html"  # a page on the same site whose table holds the data (DPCO 2014)
        else:
            skipped.append((title, f"links off-site: {url}"))
            continue
        documents.append(
            NppaDocument(section, _doc_id(url), title, url, file_type, page_url, None, size_text)
        )
    return documents, skipped


def order_documents(page: str, page_url: str) -> list[NppaDocument]:
    """One PDF per row of the orders feed."""
    tables = [table for table in parse_tables(page) if table.headers == ORDERS_HEADERS]
    if not tables or not tables[0].rows:
        raise UnexpectedResponseError(f"{page_url}: no orders table")
    documents = []
    for row in tables[0].rows:
        if len(row) != 4 or row[3][1] is None or not _is_pdf(row[3][1]):
            raise UnexpectedResponseError(f"{page_url}: unexpected order row {row!r}")
        (_, _), (date_text, _), (title, _), (size_text, href) = row
        try:
            order_date = datetime.strptime(date_text, "%d-%b-%Y").date()  # e.g. "04-Nov-2026"
        except ValueError:
            raise UnexpectedResponseError(f"{page_url}: unexpected date {date_text!r}") from None
        url = urljoin(page_url, html.unescape(href))
        documents.append(
            NppaDocument("orders", _doc_id(url), title, url, "pdf", page_url, order_date, size_text)
        )
    return documents


class Nppa:
    def __init__(self, fetcher: PoliteFetcher, store: RawStore, site_url: str = SITE):
        self.fetcher = fetcher
        self.store = store
        self.site_url = site_url  # tests point this at a local fake site

    def list_documents(self, sections: list[str]):
        """Fetch the listing page of each section (1 request each) and collect its documents."""
        documents: list[NppaDocument] = []
        skipped: list[tuple[str, str]] = []
        for section in sections:
            if section == "orders":
                documents += order_documents(*self._page(ORDERS_PATH))
            elif section in REFERENCE_PATHS:
                found, rows = reference_documents(*self._page(REFERENCE_PATHS[section]), section)
                documents += found
                skipped += rows
            else:
                raise ValueError(f"section must be one of {SECTIONS}, not {section!r}")
        return documents, skipped

    def download(self, document: NppaDocument, *, refresh: bool = False) -> DocumentResult:
        """Download one document (1 request) unless it's already stored."""
        if not refresh and self.store.has_item(document.prefix):
            return DocumentResult(document, "skipped")
        result = self.fetcher.fetch(document.url)
        if document.file_type == "pdf" and not result.content.startswith(b"%PDF-"):
            raise UnexpectedResponseError(f"{document.url}: not a PDF ({result.content[:40]!r})")
        if document.file_type == "html" and b"<table" not in result.content.lower():
            raise UnexpectedResponseError(f"{document.url}: the page no longer has a data table")
        stored = self.store.put(
            document.prefix,
            result.content,
            document.file_type,
            {
                "source": SOURCE,
                "method": "auto",
                "dataset": document.section,
                "title": document.title,
                "order_date": document.order_date.isoformat() if document.order_date else None,
                "listing": {"url": document.listing_url, "size_text": document.size_text},
                "request": result.provenance(),
            },
        )
        return DocumentResult(document, "stored" if stored.created else "unchanged", stored.key)

    def _page(self, path: str) -> tuple[str, str]:
        """Fetch a listing page; return (its text, its final URL)."""
        result = self.fetcher.fetch(self.site_url + path)
        return result.content.decode("utf-8", errors="replace"), result.final_url


def _is_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def _doc_id(url: str) -> str:
    """'.../Compendium-Prices-2022pdf-464b...pdf' -> 'compendium-prices-2022pdf-464b...'."""
    name = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
    doc_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")  # safe inside a storage path
    if not doc_id:
        raise UnexpectedResponseError(f"can't make a document id from {url!r}")
    return doc_id


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download NPPA ceiling-price documents into raw/.")
    parser.add_argument(
        "--section", action="append", choices=SECTIONS, help="repeatable (default: all sections)"
    )
    which = parser.add_mutually_exclusive_group(required=True)  # exactly one of these
    which.add_argument("--list", action="store_true", help="show the documents; download nothing")
    which.add_argument("--doc-id", action="append", help="download this document; repeatable")
    which.add_argument("--all", action="store_true", help="download every listed document")
    parser.add_argument(
        "--refresh", action="store_true", help="re-download documents already stored"
    )
    args = parser.parse_args(argv)

    nppa = Nppa(PoliteFetcher(), RawStore.from_env())
    documents, skipped = nppa.list_documents(args.section or SECTIONS)
    if args.list:
        for doc in documents:
            when = doc.order_date.isoformat() if doc.order_date else "-"
            name = doc.doc_id[:45]
            print(f"{doc.section:<14} {when:<10} {doc.file_type:<4} {name:<45} | {doc.title}")
        for title, reason in skipped:
            print(f"{'skip':<14} {reason} | {title}")
        print(f"{len(documents)} documents, {len(skipped)} rows skipped")
        return
    if args.doc_id:
        unknown = set(args.doc_id) - {doc.doc_id for doc in documents}
        if unknown:
            parser.error(f"not in the listed documents: {sorted(unknown)} (see --list)")
        documents = [doc for doc in documents if doc.doc_id in args.doc_id]
    for doc in documents:
        result = nppa.download(doc, refresh=args.refresh)
        where = f" -> raw/{result.key}" if result.key else ""
        print(f"{doc.section} {doc.doc_id}: {result.outcome}{where}")


if __name__ == "__main__":
    main()
