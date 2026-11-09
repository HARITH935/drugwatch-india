"""Family B: CDSCO NSQ lists, Apr 2024 - Jun 2025, central and state (data-sources.md §7.1).

8 columns. Two names for the drug column: "Name of Drugs/medical device/cosmetics" (2024) and
"Product/Drug Name" (2025). Up to Feb 2025 a section row ("A. CDSCO/Central Laboratories",
"B. State Laboratories") comes before the header. Apr 2024 page 4 is drawn as a 12-column grid; the
engine's position matching maps it back to these fields (table_parser.py).
"""

from drugwatch_extraction.rows import ParseResult
from drugwatch_extraction.table_parser import Vocabulary, parse_tables

VOCABULARY: Vocabulary = (
    ("serial_no", ("s.no", "sl.no", "s.n.")),  # Apr 2024 prints "S." / "N." on two lines
    ("product_name", ("product/drugname", "nameofdrugs")),
    ("batch_no", ("batchno",)),
    ("mfg_date", ("manufacturingdate", "dateofmanufacture")),
    ("expiry_date", ("expirydate", "dateofexpiry")),
    ("manufacturer", ("manufacturedby",)),
    ("failure_reason", ("nsqresult",)),  # printed as "NSQ Result"
    ("reported_by", ("reportedby",)),  # the lab that tested the sample
)
FIELDS = tuple(field for field, _ in VOCABULARY)


def parse_family_b(data: bytes) -> ParseResult:
    return parse_tables(data, VOCABULARY)
