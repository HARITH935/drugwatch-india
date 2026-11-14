r"""Phase 3 step 6: sort free-text failure reasons into standard categories.

`failure_reason` is what the lab wrote, in whatever words it used: **3,730 distinct values** over
8,317 real rows once case and line breaks are normalised, and the 800 most common still cover only
61.5% of rows. A lookup table is hopeless, so categories are matched on the TEXT.

Three decisions Harith made before this was written (2026-11-13), each with the evidence:

1. **A list, not one value per row.** 1,183 real rows (14%) report more than one failed test
   ("Dissolution and Assay", "ph, particulate matter and description"), 175 of them three or
   more. `failure_categories` is an array, like `strengths` already is, so a row that failed two
   tests is counted under both instead of having one silently dropped.

2. **The vocabulary is wider than the plan's 7** (ADR 0009). The plan names Assay, Dissolution,
   Sterility, Description, Particulate, Spurious and Other; on the real archive those leave 17.5%
   of rows in "Other", including every pH (97 rows), Content (153), Related Substances (95),
   Uniformity (53) and Water (37) failure - "Other" would be the second-largest category on a
   dashboard, which tells a reader nothing.

3. **"Content" counts as Assay.** An assay IS a content determination and CDSCO writes both for
   the same finding ("assay/content of cholecalciferol" appears as one phrase). But `water
   content` and `moisture content` are the Water test, and `uniformity of content` is the
   Uniformity test, so both are excluded from Assay by name.

**Spurious comes from `is_spurious`, never from the text** (CLAUDE.md Section 6). The word
"spurious" appears in the reason text of rows that are ordinary NSQ findings - one real value ends
"...the tests for identification and assay spurious" - so matching the word would mark 264 rows
spurious when only 77 are. A spurious row still gets its lab-test categories too: the tests were
really run, on the seized counterfeit sample. Nothing is attributed to a manufacturer either way,
because build_silver already leaves every manufacturer column NULL on those rows.

Matching rules, all checked against the real values:
- The text is lower-cased and its whitespace collapsed first. clean_text.py keeps line breaks on
  purpose, so "dissolution (for calcium)" and "dissolution (for\ncalcium)" are two distinct raw
  values (48 and 24 rows) that must land in one category.
- Every pattern is bounded with `\b...\b` or `(?!\w)`. Short tokens are the reason: `bet`
  (bacterial endotoxin test, 9 rows) would otherwise match "diabetes" and "betamethasone", and
  `ph` would match "graph" and "morphine".
- Real misspellings are matched as spelled, not corrected: `misbrandad` (13 rows), `sterillity`
  (6), `alochol` (6). A typo in CDSCO's text is not a reason to lose the row's category.
- A reason naming no test at all ("nsq", "not applicable", "does not conform to i.p.") gets
  `Other`, the same as an unrecognised one: both mean "we cannot say which test failed".

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.failure_category
"""

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

# Order is the order categories appear in the array, so the output reads the same way every time.
# Each pattern runs against the lower-cased, whitespace-collapsed text.
CATEGORIES: tuple[tuple[str, str], ...] = (
    # An assay is a content determination, so "content" belongs here (decision 3) - except the
    # three phrases where "content" names a different test entirely.
    (
        "Assay",
        r"\bassay\b|\bpotency\b|\benzymatic activity\b|"
        r"(?<!water )(?<!moisture )(?<!uniformity of )\bcontent\b",
    ),
    ("Dissolution", r"\bdissolution\b|\bdissolutin\b"),
    # A separate test from dissolution (it measures the tablet breaking up, not the drug going
    # into solution) and reported on its own in 114 real rows, so not folded into it.
    ("Disintegration", r"\bdisintegrat"),
    # "bet" is the Bacterial Endotoxin Test; bounded, or it matches diabetes/betamethasone.
    (
        "Sterility",
        r"\bsteril|\bsterillity\b|\bendotoxin|\bbet\b|\bmicrobial\b|\bpyrogen|"
        r"\baerobic\b|\bviable count\b|\bfungal\b",
    ),
    # `appear` as a prefix, not `\bappearance\b`: one real value reads "mottled appeareance".
    # A spot/visual defect is a description failure too ("presence of spot defect was observed").
    (
        "Description",
        r"\bdescription\b|\bdescriptive\b|\bappear|\bcolou?r|\bodou?r\b|"
        r"\bspot defect\b|\bspots? (all over|were observed|was observed)\b|"
        r"\bpresence of spots?\b|\bmottled\b",
    ),
    ("Particulate", r"\bparticulate\b|\bparticle|\bclarity\b|\bvisible particles?\b"),
    # "negative for the presence of tamsulosin" and "positive result for the presence of
    # diclofenac" (an allopathic drug found in an ayurvedic preparation) are both identity
    # findings: the test asked which substance is in the pack, and got the wrong answer.
    (
        "Identification",
        r"\bidentification\b|\bidentity\b|(negative|positive result) for the presence\b",
    ),
    # Bounded hard: "ph" is two letters and sits inside graph, morphine, phosphate...
    ("pH", r"\bph\b|\bp\.h\.?(?!\w)|\balkalinity\b|\bacidity\b"),
    # "susbtances" is a real misspelling in 3 rows.
    # Heavy metals are an inorganic impurity, reported the same way ("it fails the test for
    # heavy metals (as pb) parts per million").
    ("Related substances", r"\brelated su[bs]?s?[bt]?tances?\b|\bimpurit|\bheavy metals?\b"),
    # `\bunifor` as a prefix covers uniformity, uniformly and the real misspellings
    # "uniformely" and "uniformaly"; no other English word starts that way.
    ("Uniformity", r"\bunifor"),
    # "water for injection" is the PRODUCT, not the water-content test: 8 real rows read
    # "sterility of water for injection" / "bacterial endotoxins for sterile water for injection".
    ("Water", r"\bwater content\b|\bmoisture\b|\bloss on drying\b|\bwater\b(?! for injection)"),
    # Physical measures reported as their own failure: weight per ml, net weight, length,
    # extractable volume, specific gravity, relative density, fineness, neps (cotton defects).
    (
        "Physical",
        r"\bphysical (aspect|parameter)|\bweight per ml\b|\bnet weight\b|\blength\b|"
        r"\bvolume\b|\bspecific gravity\b|\brelative density\b|\bfineness\b|\bbrittle\b|"
        r"\boptical rotation\b|\bdiameter\b|"
        r"\bneps\b|\bskewness\b|\bswelling\b|\bmatter insoluble in al(co|oc)hol\b",
    ),
    # A labelling offence, NOT a counterfeit: "misbranded" means the label was wrong or
    # incomplete. Calling it Spurious would accuse a maker of counterfeiting (CLAUDE.md Section 6).
    #
    # This one is an ALLOW-LIST of the phrasings CDSCO really uses for a labelling offence, not
    # the word "label" with exceptions carved out - because in this archive "label" usually means
    # the DECLARED STRENGTH, not the printed label:
    #     "does not conform to LABEL CLAIM with respect to the content of ketoconazole"  (105)
    #     "the content of vitamin d3 is less (i.e. 34.85% of the LABELLED AMOUNT)"        (42)
    #     "does not conform to LABEL with respect to the content of available iodine"      (2)
    #     "against LABELLED CLAIM of 2500 mg per ml"                                       (2)
    # Every one of those is a strength shortfall, already counted under Assay by "content of".
    # Matching the bare word reported 390 labelling offences where the archive holds about a
    # quarter of that, and each exception only moved the goalposts. Mislabelling is an accusation,
    # so this category stays conservative in the same way manufacturer merging does (CLAUDE.md
    # Sections 5 and 6): a missed category is better than a wrong accusation.
    (
        "Labelling",
        r"\bmisbrand|\bincorrect label|\blabel?ling\b|\blabeling\b|\blabel review\b|"
        r"\bon the label\b|\bproduct label\b|\blabel of the container\b|\blabelled as\b|"
        r"\bnot printed on\b|\bprinted on the strip",
    ),
)
SPURIOUS_CATEGORY = "Spurious"  # set from is_spurious, never from the reason text
OTHER = "Other"  # a reason that names no test we recognise, or names none at all


def normalized_reason(reason: Column) -> Column:
    """Lower-cased, whitespace-collapsed text - so a reason split across a line break by the PDF
    matches the same pattern as the same reason written on one line."""
    return F.lower(F.trim(F.regexp_replace(reason, r"\s+", " ")))


def categories_of(reason: Column, is_spurious: Column) -> Column:
    """The categories this row's failure reason falls into, as an array.

    Empty only when no reason was reported at all. A reason we cannot place becomes ["Other"], so
    nothing is silently dropped and step 8's GE suite can watch the Other share for drift.
    """
    text = normalized_reason(reason)
    has_reason = text.isNotNull() & (text != "")
    matched = [F.when(text.rlike(pattern), F.lit(name)) for name, pattern in CATEGORIES]
    # array_compact drops the nulls from the patterns that did not match.
    found = F.array_compact(F.array(*matched))
    # F.array() with no arguments is array<void>, which array_union refuses to combine with
    # array<string>, so the empty case is cast explicitly.
    empty = F.array().cast("array<string>")
    with_other = F.when(F.size(found) > 0, found).otherwise(F.array(F.lit(OTHER)))
    reason_categories = F.when(has_reason, with_other).otherwise(empty)
    spurious = F.when(is_spurious, F.array(F.lit(SPURIOUS_CATEGORY))).otherwise(empty)
    return F.array_union(spurious, reason_categories)


def add_failure_categories(df: DataFrame) -> DataFrame:
    """Add `failure_categories` (array of category names) to a silver-shaped DataFrame."""
    return df.withColumn(
        "failure_categories", categories_of(F.col("failure_reason"), F.col("is_spurious"))
    )


def main() -> None:
    """Report the real spread of categories (read-only; reads the written silver table).

    Run (from spark/, RustFS up):
        uv run --env-file ../.env python -m drugwatch_spark.failure_category
    """
    from drugwatch_spark.build_silver import SILVER
    from drugwatch_spark.session import spark_session

    spark = spark_session("failure-category")
    try:
        df = add_failure_categories(spark.read.parquet(SILVER)).cache()
        total = df.count()
        print(f"{total} rows\n")

        exploded = df.select(
            "failure_reason", F.explode("failure_categories").alias("category")
        ).cache()
        print("rows per category (a row can be in more than one):")
        for row in exploded.groupBy("category").count().orderBy(F.desc("count")).collect():
            print(f"  {row['category']:20} {row['count']:5} ({row['count'] / total:.1%})")

        sizes = df.select(F.size("failure_categories").alias("n"))
        print("\ncategories per row:")
        for row in sizes.groupBy("n").count().orderBy("n").collect():
            print(f"  {row['n']} categories: {row['count']} rows")

        other = df.where(F.array_contains("failure_categories", OTHER))
        print(f"\n'Other' rows: {other.count()} - the most common reasons behind them:")
        by_text = (
            other.select(normalized_reason(F.col("failure_reason")).alias("reason"))
            .groupBy("reason")
            .count()
            .orderBy(F.desc("count"))
        )
        for row in by_text.limit(25).collect():
            print(f"  {row['count']:4}  {row['reason'][:88]}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
