"""Phase 3 step 4, piece 3: split brand from generic/salt, only where the pattern is unambiguous.

The hardest piece, on purpose last. Real names have no reliable order (brand first or generic
first, both happen) and often no separator at all ("Rosuvas F 20 Tablets Rosuvastatin and
Fenofibrate Tablets IP" just runs them together) - splitting on a guess would silently get a real
fraction wrong, so this only attempts a split where the SHAPE itself proves which side is which.

Checked against all 8,322 real names first (2026-11-13), in two stages:

1. Shape: does the name have exactly one top-level bracket group - "(...)" or "[...]", brackets
   nested inside it don't count as a second group? 50% of PDF names, 36% of portal NSQ names do.
   Zero groups (no separator to split on), 2+ groups (combination packs, multi-part vaccines) and
   unbalanced brackets (a cut-off cell) all stay null - genuinely too ambiguous for this slice.

2. Side: of the one group's two sides (inside the brackets, and everything outside them), which
   is the generic/composition? Checked two signals against the real single-group names:
   - a dosage-form word (Tablets, Injection...) on exactly one side: 63.5% of names, but 29.5%
     have the form word on BOTH sides (a brand like "Pemolate Suspension" repeats the dosage form,
     so this signal alone is too often ambiguous to trust);
   - an official pharmacopoeia marker (IP, BP, USP, in any of their dotted forms) on exactly one
     side: only 58.5% of names (weaker reach), but only 1.9% ambiguous (both sides) - a brand name
     essentially never carries an official pharmacopoeia designation, so this signal is trusted.
   Pharmacopoeia marker wins: the side WITH the marker is the generic/composition, the other side
   is the brand. Checked real examples of both orders ("Ampicillin ... I.P. (AMPIVEE-500)" - marker
   outside; "Senocartine (Levocarnitine ... USP ...)" - marker inside, reversed order, caught
   correctly) and the marker-on-both/neither cases (duplicate descriptions, vaccines) - correctly
   left null rather than guessed.

3. Sanity checks on the result, found by reading the real output of stages 1-2, not assumed safe.
   One more, cheapest first: a generic side that is JUST the marker ("ABSORBENT COTTON WOOL (IP)"
   -> generic "IP") has no real composition in it either - 1 real occurrence, but free to catch.

   52 of 1,860 splits (2.8%) had a "brand" that was really just the strength on its own
   ("Ferrous ascorbate & folic acid tablet IP (100mg/1.5mg)" split brand="100mg/1.5mg"). The
   marker correctly sat on only one side; that side just didn't happen to be a real brand name.
   looks_like_a_brand() rejects a candidate with no letter outside a unit word (mg, ml, IU, w/v,
   ...); the split is dropped (both sides null) rather than kept with a non-brand "brand".

   A second sanity check, same reason: "Ringer Lactate Solution for Injection" (and 4 more
   spellings of it, 29 occurrences) kept passing as a "brand" - it is a second, synonym
   description of the SAME composition (Compound Sodium Lactate), not a brand. The giveaway is
   grammatical: "for Injection" describes a route, the way a brand is never named. Checked this
   guard against all 62 real multi-word brand candidates found while checking this: it rejects
   only the 5 Ringer Lactate spellings, keeping every genuine one ("DOLOSAFE D TABLETS", "Phena
   Kid Syrup", ...) untouched, even though those also end in a dosage-form word.

Named split_brand_name/split_generic_name, not brand_name/generic_name: portal NSQ rows already
have their OWN brand_name bronze column (13.8% real values, rest "NA"-style placeholders),
and overwriting it here would silently discard those real portal values. Reconciling the two is
left to the gold layer (dbt); this module only adds new columns, bronze and existing columns are
never touched.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.brand_generic
"""

import re

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

PHARMA = re.compile(r"\b(?:I\.?P\.?|B\.?P\.?|U\.?S\.?P\.?)\b", re.IGNORECASE)
_RESULT_TYPE = StructType(
    [StructField("split_generic_name", StringType()), StructField("split_brand_name", StringType())]
)


def bracket_groups(text: str) -> list[tuple[int, int]] | None:
    """Top-level ( ) / [ ] groups as (start, end) char spans; nested brackets count as one group;
    None if the brackets in `text` don't balance (a cut-off cell: never guessed)."""
    depth, start, groups = 0, None, []
    for i, ch in enumerate(text):
        if ch in "([":
            if depth == 0:
                start = i
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                groups.append((start, i))
    return groups if depth == 0 else None


def tidy(text: str) -> str:
    """Line breaks and runs of whitespace -> one space; stray leading/trailing punctuation gone."""
    return " ".join(text.split()).strip(" ,.-")


# The dosage-form words a composition description uses ("...Solution FOR Injection"), reused from
# dosage_form.py's own vocabulary; a real brand is never named "for" a route of administration.
_FORM_WORD = r"tablets?|tabs?|capsules?|caps?|injections?|inj|infusions?|syrups?|suspensions?|solutions?|drops?"  # noqa: E501
FOR_A_ROUTE = re.compile(rf"\bfor\s+(?:{_FORM_WORD})\b", re.IGNORECASE)


def looks_like_a_brand(text: str) -> bool:
    """False for a candidate that is really a strength or a second composition description, not
    a brand name:
    - no letter outside a strength (e.g. "100mg/1.5mg"). Reuses strength.py's STRENGTH pattern,
      already proven on this archive's real units and glued-digit shapes ("100mg"), rather than a
      second, weaker one;
    - "... for Injection" and the like: a real brand is never named for its route (e.g. "Ringer
      Lactate Solution for Injection" is a second, synonym description of Compound Sodium
      Lactate, not a brand - checked against all 62 real multi-word candidates found while
      checking this: only the 5 real spellings of this one phrase are rejected, every genuine
      multi-word brand found ("DOLOSAFE D TABLETS", "Phena Kid Syrup", ...) is kept)."""
    from drugwatch_spark.strength import STRENGTH

    if not re.search(r"[A-Za-z]", STRENGTH.sub("", text)):
        return False
    return not FOR_A_ROUTE.search(text)


def split_brand_generic(name: str | None) -> dict[str, str | None]:
    """generic/brand if `name` has exactly one bracket group with the marker on exactly one side,
    and that side's non-marked twin is a real brand, not a bare strength; both None otherwise."""
    nothing = {"split_generic_name": None, "split_brand_name": None}
    if not name:
        return nothing
    groups = bracket_groups(name)
    if groups is None or len(groups) != 1:
        return nothing
    start, end = groups[0]
    inside, outside = name[start + 1 : end], name[:start] + " " + name[end + 1 :]
    inside_has, outside_has = bool(PHARMA.search(inside)), bool(PHARMA.search(outside))
    if inside_has and not outside_has:
        generic, brand = tidy(inside), tidy(outside)
    elif outside_has and not inside_has:
        generic, brand = tidy(outside), tidy(inside)
    else:
        return nothing  # marker on both sides (a duplicate description) or neither: not guessed
    if not PHARMA.sub("", generic).strip():
        return nothing  # e.g. "ABSORBENT COTTON WOOL (IP)": nothing there but the marker itself
    if not looks_like_a_brand(brand):
        return nothing  # e.g. "(100mg/1.5mg)": the marker-free side is a strength, not a brand
    return {"split_generic_name": generic, "split_brand_name": brand}


_split_udf = F.udf(split_brand_generic, _RESULT_TYPE)


def add_brand_generic(df: DataFrame, name: Column) -> DataFrame:
    split = _split_udf(name)
    return df.withColumn("split_generic_name", split["split_generic_name"]).withColumn(
        "split_brand_name", split["split_brand_name"]
    )


def main() -> None:
    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("brand-generic")
    try:
        pdf_name = F.col("product_name")
        portal_name = F.coalesce(F.col("generic_name"), F.col("product_name"))
        datasets = [
            ("PDF", read_bronze(spark, PDF), pdf_name),
            ("Portal", read_bronze(spark, PORTAL), portal_name),
        ]
        for label, raw_df, name in datasets:
            df = add_brand_generic(raw_df, name).cache()
            total = df.count()
            split = df.where(F.col("split_generic_name").isNotNull()).count()
            print(f"\n{label}: {total} rows, {split} split ({split / total:.1%})")
            for row in df.where(F.col("split_generic_name").isNotNull()).select(
                name.alias("name"), "split_generic_name", "split_brand_name"
            ).limit(6).collect():  # fmt: skip
                print(f"  {' '.join(row['name'].split())[:60]!r}")
                print(
                    f"    generic={row['split_generic_name']!r} brand={row['split_brand_name']!r}"
                )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
