"""Phase 3 step 5, piece 1: clean the manufacturer field, before RapidFuzz matching in piece 2.

The `manufacturer` field holds the company name AND its full postal address in one string,
usually comma-separated ("M/s. Panther Health Care Pvt. Ltd., Plot No.318, Roorkee..."). Checked
against all 8,271 real values first (2026-11-13):

- Boundary: the first comma, if there is one (97.4% of values). Where there is no comma but a
  legal suffix (Pvt. Ltd., Limited, LLP...) is found, the suffix's end is the boundary instead
  (checked: when both exist, the suffix sits right at the comma anyway, so using the comma alone
  is simpler and gives the same result almost every time).
- "(A Unit of ...)"/"(A Division of ...)"/"(A Subsidiary of ...)" right after that boundary is
  part of the identifying name, not the address (49 real occurrences, 2 real companies, e.g.
  "M/s. Paschim Banga Pharmaceuticals, (A Unit of Farista Vanijya Pvt. Ltd), NH-31, ..."): the
  real boundary is pushed to the NEXT comma, after that aside's closing bracket.
- 74 of 8,271 values (0.9%) have neither a comma nor a legal suffix anywhere ("Affy Parenterals
  Vill. Gullawala P.O Baddi Distt. Solan 173205 (HP)") - no reliable signal to cut on. Left
  untouched (the whole text stays as the name, address null) rather than guessed; a few of these
  are also letter-spaced ("A c c u r a C a r e..."), the same problem clean_text.py deferred.
- Placeholders ("Spurious", "Not applicable", "Under Investigation", ...) -> both null. The
  portal spurious tab's own manufacturer is the name on a FAKE pack (CLAUDE.md Section 6) and in
  the real data is ALWAYS exactly "Under Investigation" anyway, so this already keeps it out.

Case is left exactly as printed (not title-cased): many real names are already ALL CAPS, and some
of those are genuine acronyms ("JKMSCL") that title-casing would turn into "Jkmscl" - worse to
read, and unnecessary, since step 5 piece 2's RapidFuzz call can compare case-insensitively on
its own (its own `default_process`), without this module needing to decide display casing.

clean_manufacturer_name() adds manufacturer_name (the address-stripped, M/s.-stripped name, with
Pvt./Ltd. spelled out) and manufacturer_address; both null for a placeholder or missing value.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.manufacturer_name
"""

import re

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

PLACEHOLDER = {
    "spurious", "not mentioned", "not applicable", "under investigation",
    "vials received without label", "nil", "n/a", "nm", "--", "-",
}  # fmt: skip
PREFIX = re.compile(r"^\s*M\s*/\s*[Ss]\.?\s*", re.IGNORECASE)
SUFFIX = re.compile(
    # (?!\w), not a trailing \b: \b after an optional "." fails when a non-word character follows
    # it directly ("Ltd." before a comma) - found the same way as brand_generic.py's PHARMA bug.
    r"Pvt\.?\s*Ltd\.?(?!\w)|Private\s+Limited(?!\w)|\bLtd\.?(?!\w)|\bLimited(?!\w)|\bLLP(?!\w)",
    re.IGNORECASE,
)
OWNERSHIP_ASIDE = re.compile(
    r"^\s*\(\s*A\s+(?:Unit|Division|Subsidiary)\s+of\b[^)]*\)", re.IGNORECASE
)
ABBREVIATIONS = (
    (re.compile(r"\bPvt\.?(?!\w)", re.IGNORECASE), "Private"),
    (re.compile(r"\bLtd\.?(?!\w)", re.IGNORECASE), "Limited"),
)
_RESULT_TYPE = StructType(
    [
        StructField("manufacturer_name", StringType()),
        StructField("manufacturer_address", StringType()),
    ]
)


def name_address_boundary(text: str) -> int | None:
    """Index right after the company name ends, or None if there is no comma or legal suffix to
    find it with. Skips past an "(A Unit/Division/Subsidiary of ...)" aside, which is part of the
    name, to find the comma that follows it instead."""
    comma = text.find(",")
    if comma != -1:
        aside = OWNERSHIP_ASIDE.match(text[comma + 1 :])
        if aside:
            next_comma = text.find(",", comma + 1 + aside.end())
            return next_comma if next_comma != -1 else None
        return comma
    suffix = SUFFIX.search(text)
    return suffix.end() if suffix else None


def expand_abbreviations(name: str) -> str:
    for pattern, full in ABBREVIATIONS:
        name = pattern.sub(full, name)
    return name


def clean_manufacturer_name(text: str | None) -> dict[str, str | None]:
    nothing = {"manufacturer_name": None, "manufacturer_address": None}
    if not text:
        return nothing
    text = " ".join(text.split())  # line breaks and runs of whitespace -> one space
    if text.strip(" .").lower() in PLACEHOLDER:
        return nothing
    text = PREFIX.sub("", text)
    boundary = name_address_boundary(text)
    if boundary is None:
        return {"manufacturer_name": text.strip(" ,"), "manufacturer_address": None}
    name, address = text[:boundary], text[boundary:]
    name = expand_abbreviations(name).strip(" ,")
    address = address.strip(" ,") or None
    return {"manufacturer_name": name, "manufacturer_address": address}


_clean_udf = F.udf(clean_manufacturer_name, _RESULT_TYPE)


def add_clean_manufacturer_name(df: DataFrame, manufacturer: Column) -> DataFrame:
    split = _clean_udf(manufacturer)
    return df.withColumn("manufacturer_name", split["manufacturer_name"]).withColumn(
        "manufacturer_address", split["manufacturer_address"]
    )


def main() -> None:
    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("manufacturer-name")
    try:
        for label, df in (("PDF", read_bronze(spark, PDF)), ("Portal", read_bronze(spark, PORTAL))):
            cleaned = add_clean_manufacturer_name(df, F.col("manufacturer")).cache()
            total = cleaned.count()
            present = cleaned.where(
                F.col("manufacturer").isNotNull() & (F.col("manufacturer") != "")
            ).count()
            named = cleaned.where(F.col("manufacturer_name").isNotNull()).count()
            with_addr = cleaned.where(F.col("manufacturer_address").isNotNull()).count()
            no_boundary = cleaned.where(
                F.col("manufacturer_name").isNotNull() & F.col("manufacturer_address").isNull()
            ).count()
            print(f"\n{label}: {total} rows, {present} with a manufacturer value")
            print(f"  cleaned name + address found: {with_addr} ({with_addr / present:.1%})")
            print(f"  name only, no boundary found: {no_boundary} ({no_boundary / present:.1%})")
            placeholder = present - named
            print(f"  placeholder (both null):      {placeholder} ({placeholder / present:.1%})")
            for row in cleaned.where(F.col("manufacturer_address").isNotNull()).select(
                "manufacturer_name", "manufacturer_address"
            ).limit(6).collect():  # fmt: skip
                print(f"    name={row['manufacturer_name']!r}")
                print(f"    address={row['manufacturer_address'][:70]!r}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
