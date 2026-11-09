"""Family A: CDSCO vaccine NSQ lists, Jul 2017 - Apr 2023 (data-sources.md §7.1).

One page each, made in Excel, a few rows. Above the 8-column header sit a title row ("NOT OF
STANDARD QUALITY ALERT FOR THE MONTH OF ...") and "A. Central Laboratories": both are full-width
section rows to the engine (table_parser.py). Same fields as family B, "Vaccine Name" as product.

Kept as extracted for Phase 3: some "Manufactured By" cells say "Spurious", some batches are "--",
and one Feb 2018 cell holds two texts printed on top of each other ("2M0/s1 0B0i").
"""

from drugwatch_extraction.rows import ParseResult
from drugwatch_extraction.table_parser import Vocabulary, parse_tables

VOCABULARY: Vocabulary = (
    ("serial_no", ("s.no",)),
    ("product_name", ("vaccinename",)),
    ("batch_no", ("batchno",)),
    ("mfg_date", ("manufacturingdate",)),
    ("expiry_date", ("expirydate",)),
    ("manufacturer", ("manufacturedby",)),
    ("failure_reason", ("nsqresult",)),
    ("reported_by", ("reportedby",)),
)


def parse_family_a(data: bytes) -> ParseResult:
    return parse_tables(data, VOCABULARY)
