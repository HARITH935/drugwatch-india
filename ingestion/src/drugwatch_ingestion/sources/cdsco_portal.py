"""CDSCO NSQ portal adapter (cdscoonline.gov.in): the primary CDSCO source from Jan 2019 (ADR 0004).

The portal's public search page loads its data from JSON endpoints (docs/data-sources.md §1b).
We call the same endpoints with the same parameters the page itself sends, one month at a time:

    /CDSCO/reportingYears?tab=nsq                       -> [2019, 2020, ...]
    /CDSCO/publicReportingMonths?year=2026&tab=nsq      -> ["Jan", "Feb", ...]
    /CDSCO/filteredNsqDrugTable?month=Sep-2026&source=All&tab=nsq
                                                        -> {"iTotalRecords": 330, "aaData": [...]}

Each month's response is stored byte-for-byte under raw/cdsco-portal/<tab>/<YYYY-MM>/. The bytes
are Windows-1252, not UTF-8. They're decoded here only to check their shape; bronze decodes them.

Run (from ingestion/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_ingestion.sources.cdsco_portal --month 2026-09
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.store import RawStore

BASE_URL = "https://cdscoonline.gov.in"
SOURCE = "cdsco-portal"
# Fixed English names: calendar.month_abbr would change with the computer's language settings.
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

TABLE_PATHS = {  # tab -> endpoint that returns one month's table
    "nsq": "/CDSCO/filteredNsqDrugTable",
    "spurious": "/CDSCO/filteredSpuriousDrugTable",
}
# Fields every row must have (values may be blank: some rows have no expiry date).
REQUIRED_FIELDS = {
    # Seen in every real NSQ sample, 2019-2026 (data-sources.md §1b).
    "nsq": frozenset(
        {
            "str_product_name",
            "str_brand_name",
            "str_batch_no",
            "dt_manufacturing_date",
            "dt_expiry_date",
            "str_manufactured_by",
            "str_nsq_result",
            "str_reporting_source",
            "str_reported_by_lab_or_state",
            "dt_reporting_month_year",
        }
    ),
    # The columns the portal's own page displays for spurious drugs.
    "spurious": frozenset(
        {
            "product_name_from_dtl",
            "str_brand_name",
            "str_batch_no",
            "dt_manufacturing_date",
            "dt_expiry_date",
            "str_spurious_manufacturer_name",
            "str_spurious_manufactured_by",
            "str_reporting_source",
            "str_reported_by_lab_or_state",
            "dt_reporting_month_year",
        }
    ),
}


@dataclass(frozen=True)
class MonthResult:
    tab: str
    month: str  # YYYY-MM
    outcome: (
        str  # "stored" (new bytes), "unchanged" (same bytes already stored), "skipped" (no request)
    )
    rows: int | None = None  # None when skipped
    key: str | None = None  # raw/ object key, None when skipped


class CdscoPortal:
    def __init__(self, fetcher: PoliteFetcher, store: RawStore, base_url: str = BASE_URL):
        self.fetcher = fetcher
        self.store = store
        self.base_url = base_url  # tests point this at a local fake portal

    def available_months(self, tab: str) -> list[str]:
        """Every month the portal's own year/month menus offer for this tab, oldest first.

        The menus list all 12 months of a past year whether or not it has rows, so this is a list
        of months to ask for, not proof that each one has data (data-sources.md §1b).
        """
        _check_tab(tab)
        years = self._get_json("/CDSCO/reportingYears", {"tab": tab})
        try:
            year_numbers = sorted({int(year) for year in years})
        except (TypeError, ValueError):
            raise UnexpectedResponseError(f"reporting years: {years!r}") from None
        months = set()
        for year in year_numbers:
            names = self._get_json("/CDSCO/publicReportingMonths", {"year": str(year), "tab": tab})
            if not isinstance(names, list) or not set(names) <= set(MONTH_NAMES):
                raise UnexpectedResponseError(f"reporting months for {year}: {names!r}")
            months |= {f"{year}-{MONTH_NAMES.index(name) + 1:02d}" for name in names}
        return sorted(months)  # "YYYY-MM" strings sort in date order

    def download_month(self, tab: str, month: str, *, refresh: bool = False) -> MonthResult:
        """Download one month's table into raw/.

        A month already stored is skipped without any request, unless refresh=True. Recent months
        need refreshing because state labs report late; unchanged bytes are still never re-stored.
        """
        _check_tab(tab)
        month_date = _parse_month(month)
        month = month_date.strftime("%Y-%m")  # normalise, e.g. "2026-9" -> "2026-09"
        prefix = f"{SOURCE}/{tab}/{month}"
        if not refresh and self.store.has_item(prefix):
            return MonthResult(tab, month, "skipped")

        portal_month = f"{MONTH_NAMES[month_date.month - 1]}-{month_date.year}"  # e.g. "Sep-2026"
        result = self.fetcher.fetch(
            self.base_url + TABLE_PATHS[tab],
            params={"month": portal_month, "source": "All", "tab": tab},  # same as the page sends
        )
        rows = check_month_table(result.content, tab, portal_month)
        stored = self.store.put(
            prefix,
            result.content,
            "json",
            {
                "source": SOURCE,
                "method": "auto",
                "dataset": tab,
                "alert_month": month,
                "row_count": rows,
                "encoding": "cp1252",  # how bronze must decode these bytes
                "request": result.provenance(),
            },
        )
        outcome = "stored" if stored.created else "unchanged"
        return MonthResult(tab, month, outcome, rows, stored.key)

    def _get_json(self, path: str, params: dict[str, str]) -> Any:
        result = self.fetcher.fetch(self.base_url + path, params=params)
        return _parse_json(result.content, path)


def check_month_table(content: bytes, tab: str, portal_month: str) -> int:
    """Check that a month table looks the way it always has; return its row count.

    Raises UnexpectedResponseError if anything is off, so a changed portal stops the run loudly
    instead of filling raw/ with junk (ADR 0004).
    """
    table = _parse_json(content, portal_month)
    if not isinstance(table, dict) or not isinstance(table.get("aaData"), list):
        raise UnexpectedResponseError(f"{portal_month}: response has no aaData list")
    rows = table["aaData"]
    if table.get("iTotalRecords") != len(rows):
        raise UnexpectedResponseError(
            f"{portal_month}: iTotalRecords is {table.get('iTotalRecords')!r}, rows are {len(rows)}"
        )
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise UnexpectedResponseError(f"{portal_month} row {index}: not an object")
        missing = REQUIRED_FIELDS[tab] - row.keys()
        if missing:
            raise UnexpectedResponseError(f"{portal_month} row {index}: missing {sorted(missing)}")
        # Guards against the server ignoring our month parameter and sending some other month.
        if str(row["dt_reporting_month_year"]).upper() != portal_month.upper():
            raise UnexpectedResponseError(
                f"{portal_month} row {index}: month is {row['dt_reporting_month_year']!r}"
            )
    return len(rows)


def _parse_json(content: bytes, what: str) -> Any:
    try:
        # errors="replace": one odd byte must not block a shape check (raw/ keeps the real bytes).
        return json.loads(content.decode("cp1252", errors="replace"))
    except json.JSONDecodeError:
        raise UnexpectedResponseError(f"{what}: not JSON (starts {content[:60]!r})") from None


def _parse_month(month: str) -> datetime:
    try:
        return datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise ValueError(f"month must look like 2026-09, not {month!r}") from None


def _check_tab(tab: str) -> None:
    if tab not in TABLE_PATHS:
        raise ValueError(f"tab must be one of {sorted(TABLE_PATHS)}, not {tab!r}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download CDSCO NSQ portal months into raw/.")
    parser.add_argument("--tab", choices=sorted(TABLE_PATHS), default="nsq")
    which = parser.add_mutually_exclusive_group(required=True)  # exactly one of --month / --all
    which.add_argument("--month", action="append", help="YYYY-MM; repeat for several months")
    which.add_argument("--all", action="store_true", help="every month the portal's menus offer")
    parser.add_argument("--refresh", action="store_true", help="re-download months already stored")
    args = parser.parse_args(argv)

    portal = CdscoPortal(PoliteFetcher(), RawStore.from_env())
    months = portal.available_months(args.tab) if args.all else args.month
    for month in months:
        result = portal.download_month(args.tab, month, refresh=args.refresh)
        detail = f", {result.rows} rows -> raw/{result.key}" if result.rows is not None else ""
        print(f"{result.tab} {result.month}: {result.outcome}{detail}")


if __name__ == "__main__":  # lets `python -m drugwatch_ingestion.sources.cdsco_portal` run main()
    main()
