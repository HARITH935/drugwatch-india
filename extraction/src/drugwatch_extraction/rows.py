"""What every family parser returns: rows exactly as extracted, plus what it couldn't understand.

Bronze rule (plan §7): values are kept AS EXTRACTED. A cell that wraps keeps its line breaks
("\\n"), dates stay "12/2022." and letter-spaced words stay "A s s a y". Cleaning them is Phase 3's
job, and keeping the original lets any cleaning rule be checked against what the PDF really said.

Field names are shared across families where the meaning is the same (e.g. family B's "NSQ Result"
and family C's "Reason for failure" are both `failure_reason`, the plan's failure_reason_raw).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExtractedRow:
    row_index: int  # 1-based position in the document (provenance)
    page: int  # 1-based page where the row starts (provenance)
    pages: tuple[int, ...]  # every page it spans: a row cut by a page break continues on the next
    section: str | None  # e.g. "B. State Laboratories" when the table has section rows
    fields: dict[str, str]  # field name -> cell text as extracted


@dataclass
class ParseResult:
    rows: list[ExtractedRow] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)  # fields found in the header, in order
    unknown_headers: list[str] = field(default_factory=list)  # header cells no vocabulary knew
    # Rows the parser didn't recognise: (page, reason, cells). Reported, never silently dropped.
    skipped: list[tuple[int, str, list[str]]] = field(default_factory=list)
    first_serial: int | None = None
    serial_gaps: list[int] = field(default_factory=list)  # numbers missing from first..last
