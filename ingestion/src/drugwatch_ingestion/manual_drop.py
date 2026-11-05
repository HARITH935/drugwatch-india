"""Manual drop: store a file that a PERSON downloaded in a browser into raw/ (ADR 0003 §2).

Some files can't be fetched by the downloader under our rules. Example: the NPPA 2026 Compendium
CSV, whose dashboard sits behind request signing that we never copy (ADR 0003). A person downloads
it in a normal browser, then runs this command. The file goes into raw/ like any downloaded file
(named by its hash, never overwritten), and its sidecar records who downloaded it, when, and from
which page, with method = "manual". This command makes no network requests.

Example (from ingestion/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_ingestion.manual_drop \\
        ~/Downloads/ceiling-prices.csv --source nppa --dataset compendium-2026 --period 2026-11 \\
        --page-url https://nppa.gov.in/en/compendiumofprice --downloaded-by Harith
"""

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from drugwatch_ingestion.store import RawStore, StoredObject

MAX_BYTES = 100 * 1024 * 1024  # same cap as the downloader
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")  # e.g. "nppa", "compendium-2026"
# "2026", "2026-11" (a month) or "2017-2023" (a range of years)
_PERIOD = re.compile(r"\d{4}(?:-(?:0[1-9]|1[0-2]))?|\d{4}-\d{4}")


def drop_file(
    store: RawStore,
    path: Path,
    *,
    source: str,
    dataset: str,
    period: str,
    page_url: str,
    downloaded_by: str,
    downloaded_at: datetime | None = None,
    note: str | None = None,
) -> StoredObject:
    """Check the file and its description, then store it under <source>/<dataset>/<period>."""
    for name, value in (("source", source), ("dataset", dataset)):
        if not _SLUG.fullmatch(value):
            raise ValueError(
                f"{name} must be lowercase words joined by '-', e.g. 'nppa': {value!r}"
            )
    if not _PERIOD.fullmatch(period):
        raise ValueError(f"period must look like 2026, 2026-11 or 2017-2023: {period!r}")
    url = urlsplit(page_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError(f"page URL must start with http:// or https://: {page_url!r}")
    if not downloaded_by.strip():
        raise ValueError("say who downloaded the file (--downloaded-by)")

    path = path.expanduser()
    if not path.is_file():
        raise ValueError(f"no such file: {path}")
    ext = path.suffix.lower().lstrip(".")
    if not ext.isalnum():
        raise ValueError(f"the file needs an extension such as .csv or .pdf: {path.name}")
    size = path.stat().st_size
    if not 0 < size <= MAX_BYTES:
        raise ValueError(f"{path.name} is {size} bytes: must be between 1 byte and 100 MB")
    content = path.read_bytes()
    if ext == "pdf" and not content.startswith(b"%PDF-"):
        raise ValueError(f"{path.name} ends in .pdf but isn't a PDF (a saved error page?)")

    if downloaded_at is None:  # browsers set a file's modified time to when it was downloaded
        when, when_from = datetime.fromtimestamp(path.stat().st_mtime, UTC), "file modified time"
    else:
        when, when_from = downloaded_at, "--downloaded-at"
    return store.put(
        f"{source}/{dataset}/{period}",
        content,
        ext,
        {
            "source": source,
            "method": "manual",
            "dataset": dataset,
            "period": period,
            "manual": {  # ADR 0003 §2: who, when, and the page it came from
                "downloaded_by": downloaded_by.strip(),
                "downloaded_at": when.isoformat(timespec="seconds"),
                "downloaded_at_from": when_from,
                "page_url": page_url,
                "original_filename": path.name,
                "note": note,
            },
        },
    )


def _parse_when(text: str) -> datetime:
    """'2026-11-05' or '2026-11-05T10:30' -> a datetime (UTC if no zone is given)."""
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Store a file downloaded by hand in a browser into raw/ (ADR 0003)."
    )
    parser.add_argument("file", type=Path, help="the downloaded file")
    parser.add_argument("--source", required=True, help="e.g. nppa")
    parser.add_argument("--dataset", required=True, help="e.g. compendium-2026")
    parser.add_argument("--period", required=True, help="e.g. 2026-11 (month), 2026, 2017-2023")
    parser.add_argument("--page-url", required=True, help="the page you downloaded it from")
    parser.add_argument("--downloaded-by", required=True, help="your name")
    parser.add_argument(
        "--downloaded-at", type=_parse_when, help="when, e.g. 2026-11-05 (default: file time)"
    )
    parser.add_argument("--note", help="anything worth knowing, e.g. the filters you chose")
    args = parser.parse_args(argv)

    try:
        stored = drop_file(
            RawStore.from_env(),
            args.file,
            source=args.source,
            dataset=args.dataset,
            period=args.period,
            page_url=args.page_url,
            downloaded_by=args.downloaded_by,
            downloaded_at=args.downloaded_at,
            note=args.note,
        )
    except ValueError as exc:
        parser.error(str(exc))  # prints the problem and exits with status 2, no traceback
    outcome = "stored" if stored.created else "unchanged (this exact file is already stored)"
    print(f"{outcome} -> raw/{stored.key}")


if __name__ == "__main__":
    main()
