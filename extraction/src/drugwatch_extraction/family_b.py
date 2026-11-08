"""Family B parser: CDSCO NSQ lists, Apr 2024 - Jun 2025, central and state (data-sources.md §7.1).

The table has 8 columns. pdfplumber finds tables from their ruled lines. Columns are matched by
POSITION, not by count: the header row (page 1) tells us where each column sits across the page,
and every cell on every page belongs to the header column it sits under (by its centre). So a page
drawn with extra lines (Apr 2024, page 4: a 12-column grid) still maps onto the same 8 fields.

Each row is then one of:
- the HEADER (page 1): learnt, then skipped;
- a SECTION row, e.g. "B. State Laboratories" with the other cells empty (2024 files): remembered;
- a NUMBERED row ("8." or "11"): a new record;
- a row with an EMPTY S.No: the rest of the previous record, cut by a page break: merged into it;
- anything else: reported in ParseResult.skipped, never silently dropped.
Tables with fewer than 8 columns (e.g. a 1-column footnote box) are reported and never merged.
"""

import io
import re

import pdfplumber

from drugwatch_extraction.rows import ExtractedRow, ParseResult

FIELDS = (
    "serial_no",
    "product_name",
    "batch_no",
    "mfg_date",
    "expiry_date",
    "manufacturer",
    "nsq_result",
    "reported_by",
)
_SERIAL = re.compile(r"(\d{1,4})\.?")  # "8." or "11" (the "." sometimes lands in the next cell)

Column = tuple[float, float]  # (left x, right x) of a header cell, in PDF points


def parse_family_b(data: bytes) -> ParseResult:
    result = ParseResult()
    section: str | None = None
    columns: list[Column] | None = None  # learnt from the header row
    open_rows: list[dict] = []  # rows being built: their cells can still grow on the next page
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.find_tables():
                for row, texts in zip(table.rows, table.extract(), strict=True):
                    texts = [text or "" for text in texts]  # pdfplumber gives None for empty
                    if _is_header(texts) and len(texts) == len(FIELDS):
                        columns = [(box[0], box[2]) for box in row.cells]
                        continue
                    cells = _align(row.cells, texts, columns)
                    if cells is None:
                        result.skipped.append((page_no, f"{len(texts)} columns", texts))
                        continue
                    first = cells[0].strip()
                    others_empty = not any(cell.strip() for cell in cells[1:])
                    if first and others_empty and not _SERIAL.fullmatch(first):
                        section = first
                    elif _SERIAL.fullmatch(first):
                        open_rows.append(
                            {"page": page_no, "pages": [page_no], "section": section,
                             "fields": dict(zip(FIELDS, cells, strict=True))}
                        )  # fmt: skip
                    elif not first and open_rows:
                        _continue_row(open_rows[-1], cells, page_no)
                    else:
                        result.skipped.append((page_no, "row not recognised", texts))

    for index, row in enumerate(open_rows, start=1):
        result.rows.append(
            ExtractedRow(
                row_index=index,
                page=row["page"],
                pages=tuple(row["pages"]),
                section=row["section"],
                fields=row["fields"],
            )
        )
    result.serial_gaps = _serial_gaps(result.rows)
    return result


def _is_header(texts: list[str]) -> bool:
    squashed = re.sub(r"\s+", "", "|".join(texts).lower())
    return "nsqresult" in squashed and "batch" in squashed  # only the header has both


def _align(boxes: list, texts: list[str], columns: list[Column] | None) -> list[str] | None:
    """The row's text as 8 cells, one per header column. None if it can't be placed safely."""
    if len(texts) == len(FIELDS) and columns is None:
        return texts  # nothing learnt yet (or no header): an 8-cell row maps one to one
    if columns is None or len(texts) < len(FIELDS):
        return None  # e.g. a 1-column footnote box: never glue it onto a record
    pieces: list[list[str]] = [[] for _ in FIELDS]
    for box, text in zip(boxes, texts, strict=True):
        if box is None or not text.strip():
            continue
        centre = (box[0] + box[2]) / 2
        index = min(range(len(columns)), key=lambda i: _distance(centre, columns[i]))
        pieces[index].append(text)
    return [_merge_pieces(parts) for parts in pieces]


def _distance(x: float, column: Column) -> float:
    """0 inside the column, otherwise how far outside it x lies."""
    left, right = column
    return 0.0 if left <= x <= right else min(abs(x - left), abs(x - right))


def _merge_pieces(parts: list[str]) -> str:
    """Join the texts that fell under one header column. A piece that is already contained in
    another (the same words drawn twice across split cells) is dropped."""
    kept = [part for part in parts if not any(part != other and part in other for other in parts)]
    unique = list(dict.fromkeys(kept))  # also drops exact duplicates, keeping the order
    return "\n".join(unique)


def _continue_row(row: dict, cells: list[str], page_no: int) -> None:
    """Append a continuation's non-empty cells to the row it belongs to, as new lines.

    Lines the field already has are not added again: on split-cell pages one cell can hold a whole
    address while the continuation rows repeat it line by line (Apr 2024, row 21).
    """
    for name, text in zip(FIELDS, cells, strict=True):
        existing = row["fields"][name]
        if not text.strip() or set(text.split("\n")) <= set(existing.split("\n")):
            continue
        row["fields"][name] = f"{existing}\n{text}" if existing else text
    if page_no not in row["pages"]:
        row["pages"].append(page_no)


def _serial_gaps(rows: list[ExtractedRow]) -> list[int]:
    """Serial numbers missing from 1..highest: each one is probably a row the parser missed."""
    numbers = {int(_SERIAL.fullmatch(row.fields["serial_no"].strip()).group(1)) for row in rows}
    return sorted(set(range(1, max(numbers, default=0) + 1)) - numbers)
