"""The table engine shared by the family parsers: the HEADER decides the fields.

A family is described by a VOCABULARY: for each field, the phrases its header cell can contain.
Phrases are compared with spaces removed and in lower case ("Manufactu ring Date" ->
"manufacturingdate"); a phrase starting with "=" must match the whole cell ("=from").

For each PDF:
1. A HEADER row is a row where at least 4 cells match the vocabulary, one being S.No. Its cells
   give every column a field name and an x-position. A header cell the vocabulary doesn't know
   still gets a column ("other_<words>") and is listed in ParseResult.unknown_headers. When a
   header appears again (e.g. on every page), its positions replace the old ones.
2. Every other row is ALIGNED to those positions: each cell belongs to the column it sits under
   (by its centre), so a page drawn with extra lines (split cells) maps onto the same fields.
3. The aligned row is then one of:
   - a SECTION row ("B. State Laboratories", "NCT of DELHI": first cell only): remembered;
   - a NUMBERED row ("8." or "11"): a new record;
   - a row with an EMPTY S.No: the rest of the previous record (page break): merged into it;
   - anything else: reported in ParseResult.skipped, never silently dropped.
   A table with fewer cells than the header has columns (e.g. a 1-column footnote box) is reported
   and never merged into a record.
"""

import io
import re

import pdfplumber

from drugwatch_extraction.rows import ExtractedRow, ParseResult

Vocabulary = tuple[tuple[str, tuple[str, ...]], ...]  # (field, phrases)
Column = tuple[str, float, float]  # (field, left x, right x) in PDF points

MIN_HEADER_FIELDS = 4
_SERIAL = re.compile(r"(\d{1,4})\.?")  # "8." or "11" (the "." sometimes lands in the next cell)


def parse_tables(data: bytes, vocabulary: Vocabulary) -> ParseResult:
    result = ParseResult()
    section: str | None = None
    columns: list[Column] | None = None
    open_rows: list[dict] = []  # rows being built: their cells can still grow on the next page
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.find_tables():
                for row, texts in zip(table.rows, table.extract(), strict=True):
                    texts = [text or "" for text in texts]  # pdfplumber gives None for empty
                    header = _header_columns(row.cells, texts, vocabulary, result)
                    if header is not None:
                        # The latest header wins: a file built from one table per page (family E)
                        # draws each page's columns at different positions.
                        columns = header
                        continue
                    first = texts[0].strip()
                    others_empty = not any(text.strip() for text in texts[1:])
                    # A section row is full width with only its first cell filled. A 1-cell row
                    # (a footnote box) is not one: it is reported below instead.
                    if first and len(texts) > 1 and others_empty and not _SERIAL.fullmatch(first):
                        section = first
                        continue
                    if columns is None or len(texts) < len(columns):
                        result.skipped.append((page_no, f"{len(texts)} columns", texts))
                        continue
                    cells = _align(row.cells, texts, columns)
                    serial = cells.get("serial_no", "").strip()
                    if _SERIAL.fullmatch(serial):
                        open_rows.append(
                            {
                                "page": page_no,
                                "pages": [page_no],
                                "section": section,
                                "fields": cells,
                            }
                        )
                    elif not serial and open_rows:
                        _continue_row(open_rows[-1], cells, page_no)
                    else:
                        result.skipped.append((page_no, "row not recognised", texts))

    result.columns = [field for field, _, _ in columns or []]
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
    _check_serials(result)
    return result


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _field_for(header_text: str, vocabulary: Vocabulary) -> str | None:
    squashed = _squash(header_text)
    for field, phrases in vocabulary:
        for phrase in phrases:
            if phrase.startswith("=") and squashed == phrase[1:]:
                return field
            if not phrase.startswith("=") and phrase in squashed:
                return field
    return None


def _header_columns(
    boxes: list, texts: list[str], vocabulary: Vocabulary, result: ParseResult
) -> list[Column] | None:
    """The columns this row defines if it's a header, else None."""
    named = [
        (box, text, _field_for(text, vocabulary)) for box, text in zip(boxes, texts, strict=True)
    ]
    known = [field for _, _, field in named if field]
    if len(known) < MIN_HEADER_FIELDS or "serial_no" not in known:
        return None
    columns = []
    for box, text, field in named:
        if box is None or not text.strip():
            continue  # an empty piece of a merged header cell defines no column
        if field is None:
            field = "other_" + re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
            if field not in result.unknown_headers:
                result.unknown_headers.append(field)
        columns.append((field, box[0], box[2]))
    return columns


def _align(boxes: list, texts: list[str], columns: list[Column]) -> dict[str, str]:
    """The row's text per field: each cell goes to the header column it sits under."""
    pieces: dict[str, list[str]] = {field: [] for field, _, _ in columns}
    for box, text in zip(boxes, texts, strict=True):
        if box is None or not text.strip():
            continue
        centre = (box[0] + box[2]) / 2
        field = min(columns, key=lambda column: _distance(centre, column))[0]
        pieces[field].append(text)
    return {field: _merge_pieces(parts) for field, parts in pieces.items()}


def _distance(x: float, column: Column) -> float:
    """0 inside the column, otherwise how far outside it x lies."""
    _, left, right = column
    return 0.0 if left <= x <= right else min(abs(x - left), abs(x - right))


def _merge_pieces(parts: list[str]) -> str:
    """Join the texts under one column. A piece already contained in another (the same words drawn
    twice across split cells) is dropped."""
    kept = [part for part in parts if not any(part != other and part in other for other in parts)]
    return "\n".join(dict.fromkeys(kept))  # dict.fromkeys also drops exact duplicates, in order


def _continue_row(row: dict, cells: dict[str, str], page_no: int) -> None:
    """Append a continuation's non-empty cells to its record, as new lines. Lines the field already
    has are not added again (a split cell can hold a whole address that the next rows repeat)."""
    for field, text in cells.items():
        existing = row["fields"].get(field, "")
        if not text.strip() or set(text.split("\n")) <= set(existing.split("\n")):
            continue
        row["fields"][field] = f"{existing}\n{text}" if existing else text
    if page_no not in row["pages"]:
        row["pages"].append(page_no)


def _check_serials(result: ParseResult) -> None:
    """First serial number, and numbers missing between the first and the last: each gap is
    probably a missed row. (Not from 1: a "Revised" list can hold just entry 23.)"""
    numbers = sorted(
        int(_SERIAL.fullmatch(row.fields["serial_no"].strip()).group(1)) for row in result.rows
    )
    if numbers:
        result.first_serial = numbers[0]
        result.serial_gaps = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers))
