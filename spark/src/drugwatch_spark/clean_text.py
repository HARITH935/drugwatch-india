"""Phase 3 step 2: normalize whitespace in bronze text fields (silver's first cleaning rule).

Bronze keeps values exactly as extracted (plan §7), which is right for bronze but wrong for
anything downstream: Phase 3 steps 3-7 (dates, name-splitting, manufacturer matching, failure
categories) all compare text, and two values that differ only by a stray space or a non-breaking
space would wrongly count as different.

Found by comparing real bronze data (2026-11-12): the PDF-extracted rows (Phase 2) are already
clean (table_parser.py's line-joining leaves no loose whitespace), but the CDSCO portal rows
(Phase 3 step 0) are not: 1,437 double-spaces, 12 rows with leading/trailing whitespace, 9 rows
with non-breaking spaces (U+00A0), 2 tabs. Example: "Mfg dt:  05/2018, Exp dt:  04/2020,".

What this does NOT touch, on purpose:
- line breaks ("\\n"): some are genuinely meaningful separators, not noise - e.g. one portal
  manufacturer field reads "...Ahmedabad (Gujarat)\\n\\nMrk. By : Heal Sure...": the manufacturer
  and the separate marketer, kept apart by a blank line. Collapsing it would run two different
  facts together with no space between them.
- "letter-spaced" words from PDF extraction ("A s s a y" -> "Assay"): real examples mix spaced and
  normal text on the same line ("o f D r u g s R ules, 1945"), and are not always one character
  per gap (pdfplumber sometimes fuses two characters: "v a l le y"). A blind regex here risks
  corrupting real short words and abbreviations (e.g. "G.I.D.C."); it needs its own careful pass.
"""

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F


def normalize_whitespace(df: DataFrame, columns: list[str]) -> DataFrame:
    """Clean horizontal whitespace in each of `columns`; every other column is untouched."""
    for name in columns:
        df = df.withColumn(name, _clean(F.col(name)))
    return df


def _clean(column: Column) -> Column:
    column = F.regexp_replace(column, " ", " ")  # non-breaking space -> a regular space
    # (?m): ^ and $ match at the start/end of each line, not just the whole value, so this acts
    # line by line without needing to split the string apart and lose the "\n"s that join them.
    column = F.regexp_replace(column, "(?m)^[ \t]+", "")  # a line's own leading space/tab
    column = F.regexp_replace(column, "(?m)[ \t]+$", "")  # a line's own trailing space/tab
    column = F.regexp_replace(column, "[ \t]{2,}", " ")  # a run left in the middle of a line
    return F.regexp_replace(column, r"^\s+|\s+$", "")  # the whole value's own outer edges
