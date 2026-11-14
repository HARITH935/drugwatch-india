r"""Phase 3 step 7: one row per finding, with every document that reported it kept.

The plan says "deduplicate repeated rows across central and state lists". Measured on the real
archive, that is not where the repeats are: **0** groups repeat across two documents of the same
source, and only 1 group spans a central and a state list. The real overlap is between the two
SOURCES - the portal (primary from 2019, ADR 0004) and the alert PDFs both cover Apr 2024 - Jun
2025, and 19 months carry rows from both. Of 1,186 repeated groups, **1,154 are a portal row
paired with a PDF row**, about 1,197 extra rows: ~14% of silver double-counted.

**What identifies one finding** (all five parts must be present, or the row is never merged):

    batch number + alert month + manufacturer + product + is_spurious

- **The product is in the key, and has to be.** One maker reuses batch `TST2301` across five
  different injections (Trenbolone Acetate, Trenbolone Enanthate, Nandrolone Blend, Boldenone,
  Stanozolol). Keyed on batch + month + maker alone, all ten rows collapse into one "duplicate"
  and five distinct findings become one.
- **Batch numbers that name no batch are excluded** (42 real rows): `"not applicable"` (22),
  `"not mentioned"` (7), `"nil"` (4), `"--"` (4), `"-"` (3), `"not given"`, `"na"`. Grouping on
  those merged unrelated medicines. Five of the seven are already in manufacturer_name.py's
  PLACEHOLDER set - the same "nothing to record here" text - so that set is reused rather than
  copied, plus the two spellings only seen in this column.
- **Nothing is merged on a missing key part.** Spark's `groupBy` treats NULL as a value, so
  keying on a nullable column quietly merges rows whose maker is simply unknown - which is how
  10 spurious rows first appeared to "duplicate" NSQ findings (both had no canonical maker).
  A row missing any key part gets its own group id instead, built from
  `(source_key, page, row_index)` - proven unique across all 8,322 real rows.
- **`is_spurious` is in the key** so a counterfeit report can never merge into an NSQ finding
  even if the other four parts matched (CLAUDE.md Section 6). Since `manufacturer_canonical` is
  always NULL on a spurious row, the maker part falls back to `name_on_pack`, the name printed on
  the fake pack: the right identity for matching two reports of the same counterfeit, and still
  attributed to nobody.

**Which row wins, and what it keeps** (Harith's decisions, 2026-11-13):

- **The portal row wins** (ADR 0004 makes it primary from 2019; its text is cleaner and its dates
  parse better - 95% against 90% on exactly these pairs).
- **Content columns fill gaps from the twin**, taking the first non-null value in preference
  order. This matters for 2 real rows where only the PDF carries text, one of them a firm's reply
  reading "The actual manufacturer (as per label claim) has informed that the impugned batch..." -
  a real company stating a batch is not theirs. Dropping that would be the worst kind of loss.
- **Provenance columns are NEVER blended**: `source_key`, `source_sha256`, `source_url`, `page`,
  `row_index`, `extraction_method` and `source_dataset` all describe the row that won, so a
  `page` from one document can never sit beside another document's key.
- **`also_reported_in`** lists the other documents' `source_key`s, so "this batch was published
  in both the state list and the portal" stays a fact silver can prove (CLAUDE.md Section 5).

**The bulk file is dropped**: CDSCO's "Samples declared NSQ 2017-2023" contributes 16 rows whose
batches are already reported month by month (13 of its 14 batches), which carry no alert month at
all, and whose only extra fields (status, regulatory action) are not in the silver schema. Phase 2
already found family E repeats family A. Dropping them removes the double count and every NULL
`alert_month` in one go.

**Exact matching only** (Harith's decision): about 6 cross-source pairs do not match because the
product text differs - `"Fem creme Bleach"` against `"Fem cream Bleach"`, or a PDF truncating
`"...Face and Body Cream"` to `"...Face and Body"`. They stay as two rows. Same rule as
manufacturer merging (CLAUDE.md Section 5): a missed merge is better than a wrong merge, and the
key stays something you can state in one sentence.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.deduplicate
"""

from functools import reduce

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from drugwatch_spark.manufacturer_name import PLACEHOLDER

# Batch text that names no batch. PLACEHOLDER is manufacturer_name.py's set (same kind of text);
# "not given" and "na" were only ever seen in this column.
BATCH_PLACEHOLDER = sorted(PLACEHOLDER | {"not given", "na"})
REDUNDANT_DATASET = "nsq-bulk"  # the bulk 2017-2023 file: every finding is in a monthly list too
PREFERRED_METHOD = "api"  # the portal wins a tie (ADR 0004)
# Columns that describe WHERE a row came from. Never filled from another row.
PROVENANCE = (
    "source_dataset", "source_key", "source_sha256", "source_url", "page", "row_index",
    "extraction_method",
)  # fmt: skip


def squashed(text: Column) -> Column:
    """Upper-case, letters and digits only - so `"MER3  294D"`, `"mer3-294d"` and a value broken
    across a line by the PDF all come out the same. Null when nothing is left."""
    key = F.upper(F.regexp_replace(text, r"[^A-Za-z0-9]", ""))
    return F.when(key != "", key)


def batch_key(batch_no: Column) -> Column:
    """The batch number as an identity, or null when the text names no batch."""
    collapsed = F.lower(F.trim(F.regexp_replace(batch_no, r"\s+", " ")))
    # .strip(" .") the way manufacturer_name.py does, so "N/A." matches "n/a"
    bare = F.regexp_replace(collapsed, r"^[ .]+|[ .]+$", "")
    return F.when(~bare.isin(BATCH_PLACEHOLDER), squashed(batch_no))


def maker_key(df: DataFrame) -> Column:
    """Who this finding is about: the canonical manufacturer, or - on a spurious report, where
    there is deliberately no manufacturer - the name printed on the fake pack."""
    return squashed(F.coalesce(F.col("manufacturer_canonical"), F.col("name_on_pack")))


def finding_id(df: DataFrame) -> Column:
    """One id per real-world finding, or a row-unique id when any key part is missing.

    The two cases are prefixed differently so a row that must stay alone can never collide with
    a group of rows that belong together.
    """
    parts = (
        batch_key(F.col("batch_no")),
        F.col("alert_month"),
        maker_key(df),
        squashed(F.col("product_name_raw")),
        F.col("is_spurious").cast("string"),
    )
    complete = reduce(lambda a, b: a & b, (part.isNotNull() for part in parts))
    together = F.concat_ws("\u0001", F.lit("k"), *parts)
    # Proven unique across all 8,322 real rows, so every incomplete row stays on its own.
    alone = F.concat_ws(
        "\u0001",
        F.lit("r"),
        F.col("source_key"),
        F.coalesce(F.col("page").cast("string"), F.lit("-")),
        F.col("row_index").cast("string"),
    )
    return F.when(complete, together).otherwise(alone)


def deduplicate(df: DataFrame) -> DataFrame:
    """One row per finding, gaps filled from the rows it replaces, with `also_reported_in`."""
    kept = df.where(F.col("source_dataset") != REDUNDANT_DATASET)
    grouped = kept.withColumn("_finding", finding_id(kept))

    # Preference order inside a group: the portal first, then a stable tie-break so the same row
    # wins on every run (two PDF twins of one finding would otherwise alternate).
    preference = (
        F.when(F.col("extraction_method") == PREFERRED_METHOD, 0).otherwise(1),
        F.col("source_key"),
        F.col("page").asc_nulls_last(),
        F.col("row_index"),
    )
    pick = Window.partitionBy("_finding").orderBy(*preference)
    whole = pick.rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)

    content = [c for c in df.columns if c not in PROVENANCE]
    filled = {c: F.first(F.col(c), ignorenulls=True).over(whole) for c in content}
    others = F.array_sort(
        F.array_except(F.collect_set("source_key").over(whole), F.array(F.col("source_key")))
    )
    return (
        grouped.withColumns(filled)
        .withColumn("also_reported_in", others)
        .withColumn("_rank", F.row_number().over(pick))
        .where("_rank = 1")
        .drop("_rank", "_finding")
    )


def main() -> None:
    """Report the dedup already applied to silver, and prove re-running changes nothing.

    Idempotence is the point: Phase 5 re-runs this pipeline every month, and the plan's own
    acceptance test there is "re-runs don't create duplicates".

    Run (from spark/, RustFS up):
        uv run --env-file ../.env python -m drugwatch_spark.deduplicate
    """
    from drugwatch_spark.build_silver import SILVER
    from drugwatch_spark.session import spark_session

    spark = spark_session("deduplicate")
    try:
        silver = spark.read.parquet(SILVER).cache()
        total = silver.count()
        merged = silver.where(F.size("also_reported_in") > 0)
        print(f"{total} silver rows; {merged.count()} were reported by more than one document")

        print("\nhow many documents reported one finding:")
        counts = (
            silver.select((F.size("also_reported_in") + 1).alias("documents"))
            .groupBy("documents")
            .count()
            .orderBy("documents")
        )
        for row in counts.collect():
            print(f"  {row['documents']} document(s): {row['count']} rows")

        print("\nsources that merged together:")
        pairs = merged.select(
            "source_dataset",
            F.explode("also_reported_in").alias("other"),
        ).withColumn("other_kind", F.regexp_extract("other", r"cdsco-(pdf|portal)/([^/]+)", 2))
        pairs.groupBy("source_dataset", "other_kind").count().orderBy(F.desc("count")).show(
            12, False
        )

        print(f"rows with no alert_month: {silver.where('alert_month is null').count()}")
        bulk = silver.where(F.col("source_dataset") == REDUNDANT_DATASET).count()
        print(f"rows from the redundant bulk file: {bulk} (must be 0)")

        again = deduplicate(silver.drop("also_reported_in")).count()
        print(f"\nre-running dedup on silver: {again} rows (must equal {total})")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
