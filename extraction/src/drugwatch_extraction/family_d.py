"""Family D: CDSCO combined NSQ / spurious lists, May and Aug 2018 (data-sources.md §7.1).

6 columns. The third prints FOUR values in one cell, each with a label:
    "B. No.: CBP-00711217, Mfg dt: 12/2017, Exp dt: 11/2022, Mfd by: M/s. ... Limited"
Bronze keeps that cell exactly as printed (`batch_details`) AND fills batch_no / mfg_date /
expiry_date / manufacturer by cutting at CDSCO's own labels (decided by Harith, 2026-11-09). Values
are otherwise untouched: only the comma separating two labelled parts is dropped.

A cell where a label appears twice is NOT split: in 2018 that means a two-part pack (a powder and
the liquid it's mixed with), each part with its own batch, dates and maker, and once without a
"Mfd by:" label. Guessing could pair a batch with the wrong maker, so the split fields stay empty,
the original is kept, and the row gets a warning (a "hard row" for the Phase 10 LLM fallback).
"""

import dataclasses
import re
from collections import Counter

from drugwatch_extraction.rows import ParseResult
from drugwatch_extraction.table_parser import Vocabulary, parse_tables

VOCABULARY: Vocabulary = (
    ("serial_no", ("sl.no", "s.no")),
    ("product_name", ("nameofdrugs",)),
    ("batch_details", ("batchno./dateofmanu",)),  # the combined cell, kept as printed
    ("failure_reason", ("reasonforfailure",)),
    ("drawn_by", ("drawnby",)),
    ("drawn_from", ("=from",)),
)
LABELS = (  # field, the label CDSCO prints before its value
    ("batch_no", re.compile(r"B\.\s*No\.\s*:")),
    ("mfg_date", re.compile(r"Mfg\.?\s*dt\.?\s*:")),
    ("expiry_date", re.compile(r"Exp\.?\s*dt\.?\s*:")),
    ("manufacturer", re.compile(r"Mfd\.?\s*by\.?\s*:")),
)
SPLIT_FIELDS = tuple(field for field, _ in LABELS)


def split_batch_details(cell: str) -> tuple[dict[str, str], str | None]:
    """Cut a combined cell at its labels. Returns (values, problem): values is empty when the
    cell can't be split safely, and problem says why (or notes text found before the labels)."""
    found = sorted(
        (match.start(), match.end(), field)
        for field, label in LABELS
        for match in label.finditer(cell)
    )
    counts = Counter(field for _, _, field in found)
    if any(count > 1 for count in counts.values()):
        return {}, "a label appears twice (a multi-part pack): not split"
    missing = [field for field in SPLIT_FIELDS if field not in counts]
    if missing:
        return {}, f"labels missing for {missing}: not split"
    values = {}
    for i, (_, end, field) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(cell)
        values[field] = cell[end:stop].strip().removesuffix(",").strip()
    leading = cell[: found[0][0]].strip()
    return values, (f"text before the first label: {leading!r}" if leading else None)


def parse_family_d(data: bytes) -> ParseResult:
    result = parse_tables(data, VOCABULARY)
    rows = []
    for row in result.rows:
        values, problem = split_batch_details(row.fields.get("batch_details", ""))
        if problem:
            result.warnings.append((row.row_index, problem))
        split = {field: values.get(field, "") for field in SPLIT_FIELDS}
        rows.append(dataclasses.replace(row, fields={**row.fields, **split}))
    result.rows = rows
    return result
