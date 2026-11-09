"""Family C: CDSCO spurious and combined lists, Aug 2024 - Jun 2025 (data-sources.md §7.1).

9-12 columns that drift month to month: "From" appears in Aug 2024, Sep 2024 has no "Remarks", and
Jun 2025's merged name cell gives 12 columns. The header decides which fields a file has
(table_parser.py), so the drift needs no special cases. The Jan 2025 "Revised" combined list holds a
single entry, serial 23.
"""

from drugwatch_extraction.rows import ParseResult
from drugwatch_extraction.table_parser import Vocabulary, parse_tables

VOCABULARY: Vocabulary = (
    ("serial_no", ("s.no", "sl.no")),
    ("product_name", ("nameofdrugs", "product/drugname")),
    ("batch_no", ("batchno",)),
    ("mfg_date", ("dateofmanufacture", "manufacturingdate")),
    ("expiry_date", ("dateofexpiry", "expirydate")),
    ("manufacturer", ("manufacturedby",)),
    ("failure_reason", ("reasonforfailure",)),
    ("drawn_by", ("drawnby",)),  # the inspector or office that took the sample
    ("drawn_from", ("=from",)),  # Aug 2024 only; the whole cell must be "From"
    ("firm_reply", ("firmreply", "firm’sreply", "firm'sreply")),
    ("remarks", ("remarks",)),
)


def parse_family_c(data: bytes) -> ParseResult:
    return parse_tables(data, VOCABULARY)
