"""Family F: CDSCO spurious list, Apr 2024 (data-sources.md §7.1).

9 columns, grouped by state: a full-width row such as "NCT of DELHI" or "JHARKHAND" starts each
group (a section row to the engine, table_parser.py). It records where the fake stock was sold and
what the genuine manufacturer said, instead of family C's "Reason for failure" and "Drawn By".

CAUTION for Phase 3 and the Phase 7 risk score: in a SPURIOUS list the manufacturer is the name
printed on the fake label, usually the genuine company whose brand was copied. It must never be
counted against that company (CLAUDE.md §6). The same holds for family C's spurious rows.
"""

from drugwatch_extraction.rows import ParseResult
from drugwatch_extraction.table_parser import Vocabulary, parse_tables

VOCABULARY: Vocabulary = (
    ("serial_no", ("s.no",)),
    ("product_name", ("product/drugname",)),
    ("batch_no", ("b.no", "batchno")),
    ("mfg_date", ("manufacturingdate",)),
    ("expiry_date", ("expirydate",)),
    ("manufacturer", ("manufacturedby",)),  # printed "Manufactured by as per label": see CAUTION
    ("sales_outlets", ("salesoutlets",)),  # shops the fake stock was found in or traced to
    ("manufacturer_response", ("responseoforiginal",)),  # the genuine company's reply
    ("reported_by", ("reportedby",)),
)


def parse_family_f(data: bytes) -> ParseResult:
    return parse_tables(data, VOCABULARY)
