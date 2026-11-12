"""Fix a CDSCO portal backend bug found in Phase 3 step 2 (2026-11-12).

For 9 of 7,005 portal NSQ rows (all alert_month 2019-01), the portal's own batch_no is wrong -
stale (reused from an earlier row) or has a trailing comma left on it - while the TRUE batch
number, manufacturing date, expiry date and manufacturer are all sitting correctly inside the
`manufacturer` field, as one combined, labelled cell:

    "B. No.: TP-3286,\nMfg dt: 03/2018, Exp dt: 02/2020, Mfd by: M/s. Ticoma\nPharmacia, ..."

This is exactly the combined-cell format Phase 2's family_d.py already parses for the 2018 PDFs
(same four labels, same style). split_combined_cell() below is the same cut-at-labels rule as
family_d.split_batch_details(), reimplemented here rather than imported, so Spark jobs don't pull
in pdfplumber (family_d.py's own import) for one small, self-contained, pure-text function.

The trigger is the PATTERN (manufacturer holds all four labels, each exactly once), not a list of
9 row numbers, so this also catches the same bug if it ever recurs elsewhere in the portal data.
bronze/ itself is never changed (CLAUDE.md §5): this runs in Spark, downstream of it, and the
original (wrong) values are always still there in bronze for anyone checking what the portal said.
"""

import re
from collections import Counter

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

LABELS = (  # field, the label CDSCO's text prints before its value (same as family_d.py's LABELS)
    ("batch_no", re.compile(r"B\.\s*No\.\s*:")),
    ("mfg_date", re.compile(r"Mfg\.?\s*dt\.?\s*:")),
    ("expiry_date", re.compile(r"Exp\.?\s*dt\.?\s*:")),
    ("manufacturer", re.compile(r"Mfd\.?\s*by\.?\s*:")),
)
SPLIT_FIELDS = tuple(field for field, _ in LABELS)
_RESULT_TYPE = StructType([StructField(field, StringType()) for field in SPLIT_FIELDS])


def split_combined_cell(cell: str | None) -> dict[str, str | None]:
    """Cut a combined cell at its labels; all four fields come back None when it isn't a clean,
    once-each combined cell (so the caller can tell "nothing to fix here" from a real split)."""
    nothing = dict.fromkeys(SPLIT_FIELDS)
    if not cell:
        return nothing
    found = sorted(
        (match.start(), match.end(), field)
        for field, label in LABELS
        for match in label.finditer(cell)
    )
    counts = Counter(field for _, _, field in found)
    if any(count > 1 for count in counts.values()) or any(f not in counts for f in SPLIT_FIELDS):
        return nothing  # a label repeated (a multi-part pack) or missing: don't guess
    values = {}
    for i, (_, end, field) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(cell)
        # strip(), not removesuffix(","): one real row has a double comma before the next label
        # ("Mfg dt:  08/2018,               , Exp dt: ..."), and strip() removes a whole run of
        # trailing commas/whitespace in one pass, not just a single trailing character.
        values[field] = cell[end:stop].strip(" \t\n,")
    return values


_split_udf = F.udf(split_combined_cell, _RESULT_TYPE)


def fix_combined_manufacturer_cells(df: DataFrame) -> DataFrame:
    """Where `manufacturer` is really a combined cell, replace batch_no/mfg_date/expiry_date/
    manufacturer with the values cut out of it. A row that doesn't match is untouched."""
    split = _split_udf(F.col("manufacturer"))
    with_split = df.withColumn("_split", split)
    for field in SPLIT_FIELDS:
        value = with_split[f"_split.{field}"]
        with_split = with_split.withColumn(field, F.coalesce(value, F.col(field)))
    return with_split.drop("_split")


def combined_cell_rows(df: DataFrame) -> Column:
    """True for a row whose `manufacturer` is a combined cell (used to report what changed)."""
    return _split_udf(F.col("manufacturer"))[f"{SPLIT_FIELDS[0]}"].isNotNull()


def main() -> None:
    """Report the real effect of the fix (read-only; nothing is written to silver/ yet).

    Run (from spark/, RustFS up):
        uv run --env-file ../.env python -m drugwatch_spark.fix_portal_batch
    """
    from drugwatch_spark.read_bronze import PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("fix-portal-batch")
    try:
        raw = read_bronze(spark, PORTAL)
        # Mark the affected rows BEFORE fixing anything, as a plain column. The mark expression
        # only matches the ORIGINAL manufacturer text; recomputing it against the already-fixed
        # DataFrame would find nothing, since fixed text no longer looks like a combined cell.
        marked = raw.withColumn("_combined", combined_cell_rows(raw))
        affected = marked.where("_combined").count()
        print(f"{affected} of {marked.count()} portal rows had a combined-cell manufacturer")

        fixed = fix_combined_manufacturer_cells(marked)
        cols = ["alert_month", "batch_no", "mfg_date", "expiry_date"]
        before = marked.where("_combined").select(*cols).orderBy("batch_no").collect()
        after = fixed.where("_combined").select(*cols).orderBy("batch_no").collect()
        print("\nbefore -> after:")
        for b, a in zip(before, after, strict=True):
            print(f"  {b.asDict()} -> batch_no={a['batch_no']!r} mfg_date={a['mfg_date']!r} "
                  f"expiry_date={a['expiry_date']!r}")  # fmt: skip
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
