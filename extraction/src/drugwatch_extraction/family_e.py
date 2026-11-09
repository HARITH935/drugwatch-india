"""Family E: the bulk vaccine file "Samples declared NSQ 2017-2023" (data-sources.md §7.1).

One table per page and ONE YEAR PER PAGE: page 1's title ("... regulatory action of year 2017") is
the table's first row, pages 2-5 print theirs just above the table. Serial numbers restart at 1 on
every page. So after the engine has parsed the rows (table_parser.py), each row gets its own page's
title as its section and the year as `report_year` (otherwise page 2 would inherit page 1's title),
and serial numbers are checked page by page.
"""

import dataclasses
import io
import re

import pdfplumber

from drugwatch_extraction.rows import ParseResult
from drugwatch_extraction.table_parser import Vocabulary, parse_tables

VOCABULARY: Vocabulary = (
    ("serial_no", ("s.no",)),
    ("product_name", ("nameofvaccine",)),
    ("manufacturer", ("=manufacturer",)),  # whole cell, so it can't match other headers
    ("batch_no", ("batchno",)),
    ("mfg_date", ("mfgdate",)),
    ("expiry_date", ("expdate",)),
    ("failure_reason", ("sub-standardin",)),  # printed "Sub-Standard in"
    ("sample_source", ("type/sourceofsample",)),  # who drew the sample, e.g. a Drug Inspector
    ("status", ("=status",)),
    ("regulatory_action", ("regulatoryaction",)),  # "REGULATORY ACTION/ CONCLUSION (...)"
)
_YEAR = re.compile(r"\byear\s+((?:19|20)\d\d)\b", re.IGNORECASE)


def parse_family_e(data: bytes) -> ParseResult:
    result = parse_tables(data, VOCABULARY)
    titles = _page_titles(data)
    rows = []
    for row in result.rows:
        title = titles.get(row.page)
        year = _YEAR.search(title or "")
        if year is None:
            result.warnings.append(
                (row.row_index, f"no 'year YYYY' title found on page {row.page}")
            )
        fields = {**row.fields, "report_year": year.group(1) if year else ""}
        rows.append(dataclasses.replace(row, section=title, fields=fields))
    result.rows = rows

    # Serial numbers restart on every page: each page must run 1..n.
    result.serial_gaps = []
    for page in sorted({row.page for row in rows}):
        numbers = [
            int(row.fields["serial_no"].strip().rstrip(".")) for row in rows if row.page == page
        ]
        if numbers != list(range(1, len(numbers) + 1)):
            result.warnings.append((0, f"page {page}: serial numbers {numbers} don't run 1..n"))
    result.first_serial = 1 if rows else None
    return result


def _page_titles(data: bytes) -> dict[int, str]:
    """Page number -> the title printed above its table, or inside it as the first row."""
    titles = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if not tables:
                continue
            above = page.crop((0, 0, page.width, tables[0].bbox[1])).extract_text() or ""
            first_cell = tables[0].extract()[0][0] or ""
            text = above if _YEAR.search(above) else first_cell
            titles[page_no] = " ".join(text.split())
    return titles
