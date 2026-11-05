"""CDSCO legacy PDF adapter (cdsco.gov.in): monthly NSQ / spurious alert PDFs, 2017 - Jun 2025.

The alerts page is one HTML table of about 300 notices of every kind (docs/data-sources.md §1a).
This adapter:
1. reads the table (sources/html_tables.py, built on Python's html.parser);
2. keeps the monthly NSQ / spurious lists and the bulk "Samples declared NSQ 2017-2023" file,
   and works out each list's alert month from its free-text title;
3. downloads each PDF in two hops: download_file_division.jsp?num_id=<id> returns a tiny HTML
   page whose <iframe> points at the real PDF.

Each PDF is stored under raw/cdsco-pdf/<kind>/<YYYY-MM>/<file id>/. The file id (CDSCO's own number
for the upload) keeps two documents for one month apart, e.g. an original and a "Revised" list.

Run (from ingestion/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_ingestion.sources.cdsco_pdf --list
    uv run --env-file ../.env python -m drugwatch_ingestion.sources.cdsco_pdf --file-id 12927
"""

import argparse
import base64
import binascii
import html
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, urljoin, urlsplit

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.sources.html_tables import parse_tables
from drugwatch_ingestion.store import RawStore

LISTING_URL = "https://cdsco.gov.in/opencms/opencms/en/Notifications/Alerts/"
SOURCE = "cdsco-pdf"

_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip
# "jan" / "january" / "sept" ... -> month number (fixed English names, whatever the OS language).
MONTHS = {name: number for number, name in enumerate(_MONTH_NAMES, start=1)}
MONTHS |= {name[:3]: number for name, number in list(MONTHS.items())} | {"sept": 9}

# A word, then up to 6 characters that are neither letters nor digits (", ", "-", or mis-decoded
# junk like the "â\x80\x93" in "Januaryâ\x80\x93 2025"), then a year. MONTHS decides if the word
# is a month.
_MONTH_YEAR = re.compile(r"\b([a-z]+)[^0-9a-z]{0,6}((?:19|20)\d\d)\b", re.IGNORECASE)
_YEAR_RANGE = re.compile(r"\b((?:19|20)\d\d)\s*-\s*((?:19|20)\d\d)\b")
_IFRAME_SRC = re.compile(r"""<iframe[^>]*\ssrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


@dataclass(frozen=True)
class AlertDocument:
    """One row of the alerts table that we want: a monthly list, or the bulk 2017-2023 file."""

    file_id: str  # CDSCO's number for the upload, decoded from the link's base64 num_id
    kind: str  # central-nsq / state-nsq / spurious / combined / nsq-bulk
    alert_month: str | None  # YYYY-MM; None for the bulk file
    title: str
    release_date: date
    link: str  # absolute URL of the .jsp first hop
    size_text: str  # as the table shows it, e.g. "185 KB"

    @property
    def prefix(self) -> str:
        period = self.alert_month or _YEAR_RANGE.search(self.title).group(0).replace(" ", "")
        return f"{SOURCE}/{self.kind}/{period}/{self.file_id}"


@dataclass(frozen=True)
class SkippedRow:
    """A row that mentions NSQ / spurious but isn't downloaded, and why (shown by --list)."""

    title: str
    release_date: date
    reason: str


@dataclass(frozen=True)
class DocumentResult:
    document: AlertDocument
    outcome: str  # "stored" / "unchanged" / "skipped" (already stored: no request made)
    key: str | None = None


def classify_title(title: str) -> tuple[str, str | None] | None:
    """(kind, alert month 'YYYY-MM' or None) for a document we want; None for anything else."""
    lower = title.lower()
    nsq = "nsq" in lower or "standard quality" in lower or "standard of quality" in lower
    spurious = "spurious" in lower
    if not (nsq or spurious):
        return None
    # A monthly list says "for the month of ...", or is titled like "NSQ May 2024 CDSCO Labs".
    if re.search(r"for\s+the\s+month", lower) or re.match(r"nsq\s+[a-z]+\s+\d{4}\b", lower):
        month = _find_month(title)
        if month is None:
            return None
        if nsq and spurious:
            return "combined", month
        if spurious:
            return "spurious", month
        return ("state-nsq" if "state" in lower else "central-nsq"), month
    if nsq and _YEAR_RANGE.search(title):  # "Samples declared NSQ 2017-2023"
        return "nsq-bulk", None
    return None


def _find_month(title: str) -> str | None:
    for match in _MONTH_YEAR.finditer(title):
        number = MONTHS.get(match.group(1).lower())
        if number is not None:
            return f"{match.group(2)}-{number:02d}"
    return None


def parse_listing(page: str, page_url: str = LISTING_URL) -> list[list[str | None]]:
    """The alerts table as rows of [s.no, title, release date, link, size].

    Fails loudly if the table is missing or a row doesn't have the five expected cells
    (ADR 0004: a changed format stops the run).
    """
    tables = [table for table in parse_tables(page) if table.attrs.get("id") == "example"]
    if not tables or not tables[0].rows:
        raise UnexpectedResponseError(f"{page_url}: no rows found in the alerts table")
    rows = []
    for cells in tables[0].rows:
        if len(cells) != 5 or cells[3][1] is None:
            raise UnexpectedResponseError(f"{page_url}: unexpected row {cells!r}")
        number, title, released, (_, href), size = cells
        rows.append([number[0], title[0], released[0], urljoin(page_url, href), size[0]])
    return rows


def find_documents(
    page: str, page_url: str = LISTING_URL
) -> tuple[list[AlertDocument], list[SkippedRow]]:
    """Split the listing into documents to download and NSQ/spurious rows we deliberately skip."""
    documents: list[AlertDocument] = []
    skipped: list[SkippedRow] = []
    for _, title, released, link, size in parse_listing(page, page_url):
        release_date = _parse_release_date(released)
        found = classify_title(title)
        if found is None:
            if re.search(r"nsq|spurious|standard\s+(of\s+)?quality", title, re.IGNORECASE):
                skipped.append(SkippedRow(title, release_date, "not a monthly list"))
            continue
        kind, month = found
        if month is not None and not _month_fits_release(month, release_date):
            # e.g. a typo'd year: better to skip and show it than file the PDF under a wrong month.
            skipped.append(
                SkippedRow(title, release_date, f"month {month} doesn't fit release date")
            )
            continue
        documents.append(
            AlertDocument(_file_id(link), kind, month, title, release_date, link, size)
        )
    return documents, skipped


class CdscoPdf:
    def __init__(self, fetcher: PoliteFetcher, store: RawStore, listing_url: str = LISTING_URL):
        self.fetcher = fetcher
        self.store = store
        self.listing_url = listing_url  # tests point this at a local fake site

    def list_documents(self) -> tuple[list[AlertDocument], list[SkippedRow]]:
        """Fetch the listing page (1 request) and classify its rows."""
        result = self.fetcher.fetch(self.listing_url)
        page = result.content.decode("utf-8", errors="replace")  # the page declares UTF-8
        return find_documents(page, result.final_url)

    def download(self, document: AlertDocument, *, refresh: bool = False) -> DocumentResult:
        """Download one document (2 requests: .jsp, then the PDF) unless it's already stored."""
        if not refresh and self.store.has_item(document.prefix):
            return DocumentResult(document, "skipped")

        hop = self.fetcher.fetch(document.link)  # first hop: tiny HTML page with an <iframe>
        match = _IFRAME_SRC.search(hop.content.decode("utf-8", errors="replace"))
        if match is None:
            raise UnexpectedResponseError(
                f"{document.link}: no <iframe src> in {hop.content[:200]!r}"
            )
        pdf_url = urljoin(hop.final_url, html.unescape(match.group(1)))

        pdf = self.fetcher.fetch(pdf_url)  # second hop: the real file
        if not pdf.content.startswith(b"%PDF-"):  # every PDF file starts with these 5 bytes
            raise UnexpectedResponseError(f"{pdf_url}: not a PDF (starts {pdf.content[:40]!r})")
        stored = self.store.put(
            document.prefix,
            pdf.content,
            "pdf",
            {
                "source": SOURCE,
                "method": "auto",
                "dataset": document.kind,
                "alert_month": document.alert_month,
                "file_id": document.file_id,
                "listing": {  # what the alerts table said about this file
                    "url": self.listing_url,
                    "title": document.title,
                    "release_date": document.release_date.isoformat(),
                    "size_text": document.size_text,
                },
                "first_hop_url": document.link,
                "request": pdf.provenance(),  # the PDF request: final URL, ETag, Last-Modified ...
            },
        )
        return DocumentResult(document, "stored" if stored.created else "unchanged", stored.key)


def _file_id(link: str) -> str:
    """'...download_file_division.jsp?num_id=MTI5Mjc=' -> '12927' (the id is base64-encoded)."""
    try:
        encoded = parse_qs(urlsplit(link).query)["num_id"][0]
        file_id = base64.b64decode(encoded, validate=True).decode("ascii")
    except (KeyError, binascii.Error, UnicodeDecodeError):
        raise UnexpectedResponseError(f"no usable num_id in {link!r}") from None
    if not file_id.isdigit():
        raise UnexpectedResponseError(f"num_id in {link!r} isn't a number: {file_id!r}")
    return file_id


def _parse_release_date(text: str) -> date:
    """'2025-Jul-18' -> date(2025, 7, 18)."""
    try:
        year, month, day = text.split("-")
        return date(int(year), MONTHS[month.lower()], int(day))
    except (ValueError, KeyError):
        raise UnexpectedResponseError(f"unexpected release date {text!r}") from None


def _month_fits_release(month: str, released: date) -> bool:
    """An alert list is released after its month ends, and within a year of it."""
    year, number = (int(part) for part in month.split("-"))
    months_later = (released.year - year) * 12 + (released.month - number)
    return 1 <= months_later <= 12


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download CDSCO legacy alert PDFs into raw/.")
    which = parser.add_mutually_exclusive_group(required=True)  # exactly one of these
    which.add_argument("--list", action="store_true", help="show what would be downloaded; no PDFs")
    which.add_argument("--file-id", action="append", help="download this document; repeatable")
    which.add_argument("--all", action="store_true", help="download every listed document")
    parser.add_argument(
        "--refresh", action="store_true", help="re-download documents already stored"
    )
    args = parser.parse_args(argv)

    cdsco = CdscoPdf(PoliteFetcher(), RawStore.from_env())
    documents, skipped = cdsco.list_documents()
    if args.list:
        for doc in documents:
            print(f"{doc.file_id:>6} {doc.kind:<11} {doc.alert_month or '-':<7} | {doc.title}")
        for row in skipped:
            print(f"{'skip':>6} {row.release_date} {row.reason} | {row.title}")
        print(f"{len(documents)} documents to download, {len(skipped)} NSQ/spurious rows skipped")
        return
    if args.file_id:
        unknown = set(args.file_id) - {doc.file_id for doc in documents}
        if unknown:
            parser.error(f"not in the list of documents: {sorted(unknown)} (see --list)")
        documents = [doc for doc in documents if doc.file_id in args.file_id]
    for doc in documents:
        result = cdsco.download(doc, refresh=args.refresh)
        where = f" -> raw/{result.key}" if result.key else ""
        print(f"{doc.kind} {doc.alert_month or '-'} ({doc.file_id}): {result.outcome}{where}")


if __name__ == "__main__":
    main()
