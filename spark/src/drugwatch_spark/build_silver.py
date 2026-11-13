"""Phase 3: the cleaning pipeline - bronze -> silver, one table with every cleaning step applied.

Until now each cleaning step was its own module printing its own report, and nothing ran them
together. This is the job that does, and the Parquet it writes is Phase 3's silver deliverable:
what Great Expectations (step 8) validates, what dbt loads in Phase 4, and the "cleaning job" the
Pandas vs PySpark benchmark (step 9) times.

The two sources keep different columns in bronze (PDF 37, portal 25, 18 shared), so each is
cleaned with the steps that suit it and then both are mapped onto ONE silver schema:

    PDF rows      parse_pdf_dates (5 proven formats)       product name in `product_name`
    portal rows   fix_portal_batch (9 wrong batch numbers)  name in `generic_name`, or
                  parse_dates ("Mon-YYYY"), then the PDF    `product_name` on the spurious tab
                  formats for what it can't read

Shared for both: whitespace (clean_text), dosage form, strengths, brand/generic split, the
manufacturer name split from its address, and RapidFuzz clustering - run ACROSS both sources
together, so one company spelled differently in a PDF and in the portal becomes one manufacturer.

**The spurious rule (CLAUDE.md Section 6), checked against every real spurious row:**
a spurious alert lists the name printed on a FAKE pack, which is not the maker. In this archive
that field holds one of three things:
  - "Under Investigation" (most rows);
  - a real, legitimate company whose identity was counterfeited - 7 portal rows and 10 PDF rows,
    naming Ipca, Macleods, Torrent, Mankind, Blue Cross, Medreich, Emcure, Glenmark, Sun Pharma
    and Pure and Cure;
  - a firm CDSCO says does not exist ("Pragti Remedies ... (This firm does not exist at the given
    address as per SDC, Assam ...)").
Attributing any of those would accuse a victim of counterfeiting. So on a spurious row the text
is kept as `name_on_pack` for provenance, and `manufacturer_canonical` is NULL: those rows are
counted as spurious reports, never against a manufacturer.

Not here yet, by design: `failure_category` (step 6) and de-duplication across the central and
state lists (step 7). Each will join this pipeline rather than become another separate report.

Two things step 7 is expected to settle, both measured on the real archive (2026-11-13):
  - `alert_month` is NULL on 16 rows, all of them the `nsq-bulk` family E file: CDSCO's bulk
    2017-2023 list covers many months at once and prints one year per page (`report_year`), so
    there is no single alert month to record. Those 16 are the SAME 16 findings family A already
    reports month by month, so step 7 should drop them, which removes the nulls with them. Until
    it does, silver double-counts those vaccine batches and writes them to an
    `alert_month=__HIVE_DEFAULT_PARTITION__` partition.
  - `is_spurious` is read from `source_dataset`, which is CDSCO's DOCUMENT-level category, not a
    row-level fact. 78 rows sit in documents CDSCO titles "combined NSQ/spurious". Checked: all
    78 come from the NSQ-shaped table (6-column family D, plus 1 family C row) and every
    failure_reason is a lab test (Assay, Dissolution, Sterility...), so none is a counterfeit
    report and today's data is attributed correctly. But a future combined document WITH a
    spurious section would be attributed silently, so a row-level signal is still needed.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.build_silver            # write silver
    uv run --env-file ../.env python -m drugwatch_spark.build_silver --dry-run  # count only
"""

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from drugwatch_spark.brand_generic import add_brand_generic
from drugwatch_spark.clean_text import normalize_whitespace
from drugwatch_spark.dosage_form import add_dosage_form
from drugwatch_spark.fix_portal_batch import fix_combined_manufacturer_cells
from drugwatch_spark.manufacturer_cluster import add_canonical_manufacturer
from drugwatch_spark.manufacturer_name import add_clean_manufacturer_name
from drugwatch_spark.parse_dates import parse_portal_dates
from drugwatch_spark.parse_pdf_dates import parse_pdf_dates
from drugwatch_spark.strength import add_strengths

SILVER = "s3a://silver/nsq/"
SPURIOUS = "spurious"  # the source_dataset value marking a counterfeit report

# Text columns worth whitespace-cleaning, by source (clean_text.py explains why line breaks stay).
PDF_TEXT = (
    "product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer",
    "failure_reason", "reported_by", "remarks", "firm_reply",
)  # fmt: skip
PORTAL_TEXT = PDF_TEXT + ("generic_name", "brand_name")

# The bronze values a later step OVERWRITES in place, copied aside before any step runs so silver
# can always be read against what the document actually printed. Two steps overwrite:
# normalize_whitespace (every text column) and, on portal rows, fix_combined_manufacturer_cells,
# which rewrites all four of these on the 9 rows whose manufacturer cell really holds all four.
# Taking the snapshot afterwards would leave the `_raw` columns showing the CORRECTED value and
# quietly hide the portal's own error - exactly where a reader would want to check it.
RAW_KEPT = ("batch_no", "mfg_date", "expiry_date", "manufacturer")

# What silver keeps, and where each column comes from. Nothing is invented here: every value is
# either copied from bronze or produced by a cleaning module that was checked on its own.
SILVER_COLUMNS = [
    # provenance - every row can be traced to the document it came from (CLAUDE.md Section 5)
    "source_dataset", "source_key", "source_sha256", "source_url", "page", "row_index",
    "alert_month", "extraction_method",
    # the batch this alert is about
    "batch_no", "batch_no_raw",
    # dates, as printed and as parsed
    "mfg_date_raw", "expiry_date_raw", "mfg_date", "expiry_date", "dates_valid",
    # the medicine
    "product_name_raw", "generic_name", "brand_name", "dosage_form", "strengths",
    # who made it - or, for a spurious report, the name on the fake pack
    "manufacturer_raw", "manufacturer_name", "manufacturer_address", "manufacturer_canonical",
    "is_spurious", "name_on_pack",
    # what was wrong (failure_category joins in step 6)
    "failure_reason", "reported_by", "remarks", "firm_reply",
]  # fmt: skip


def product_name_of(df: DataFrame) -> Column:
    """The medicine's name, wherever this source keeps it: portal NSQ rows use `generic_name`,
    PDF rows and the portal's spurious tab use `product_name`. Never both on one row."""
    if "generic_name" in df.columns:
        return F.coalesce(F.col("generic_name"), F.col("product_name"))
    return F.col("product_name")


def keep_raw(df: DataFrame) -> DataFrame:
    """Copy the bronze values aside as `<field>_raw` before any step changes them."""
    snapshot = {f"{field}_raw": F.col(field) for field in RAW_KEPT}
    return df.withColumns({**snapshot, "product_name_raw": product_name_of(df)})


def parse_portal_dates_with_pdf_fallback(df: DataFrame) -> DataFrame:
    """The portal's dates, falling back to the PDF formats where its own shape doesn't fit.

    Portal dates are "Mon-YYYY" in 100% of bronze values - but that was measured BEFORE
    fix_combined_manufacturer_cells, which replaces the dates on 9 rows with the text out of
    CDSCO's combined cell, and that text is written CDSCO's PDF way ("03/2018"). Verified on the
    real archive: without this fallback all 9 rows lose both dates (and `dates_valid`) even
    though the document prints them plainly.

    The fallback adds no new guesswork: it reuses parse_pdf_dates' 5 formats, each already proven
    unambiguous against every real value, and only ever fills a date the portal format left null.
    `dates_valid` is recomputed from the dates that survive, not carried over from either pass.
    """
    by_portal = parse_portal_dates(df).withColumnsRenamed(
        {"mfg_date_parsed": "_portal_mfg", "expiry_date_parsed": "_portal_expiry"}
    )
    both = parse_pdf_dates(by_portal)  # fills the same columns again, with the PDF formats
    mfg = F.coalesce(F.col("_portal_mfg"), F.col("mfg_date_parsed"))
    expiry = F.coalesce(F.col("_portal_expiry"), F.col("expiry_date_parsed"))
    return (
        both.withColumn("mfg_date_parsed", mfg)
        .withColumn("expiry_date_parsed", expiry)
        .withColumn("dates_valid", F.col("mfg_date_parsed") < F.col("expiry_date_parsed"))
        .drop("_portal_mfg", "_portal_expiry")
    )


def clean_pdf(df: DataFrame) -> DataFrame:
    """The PDF rows: whitespace, then the 5 proven date formats."""
    return parse_pdf_dates(normalize_whitespace(keep_raw(df), PDF_TEXT))


def clean_portal(df: DataFrame) -> DataFrame:
    """The portal rows: whitespace, the 9 wrong batch numbers, then the dates."""
    cleaned = normalize_whitespace(keep_raw(df), PORTAL_TEXT)
    return parse_portal_dates_with_pdf_fallback(fix_combined_manufacturer_cells(cleaned))


def clean_shared(df: DataFrame) -> DataFrame:
    """The steps that work the same on either source. Order matters: strengths needs the dosage
    form (a bare "30 g" counts only for an injection), so dosage_form must be added first."""
    name = product_name_of(df)
    with_form = add_dosage_form(df, name)
    with_strength = add_strengths(with_form, name, F.col("dosage_form"))
    with_names = add_brand_generic(with_strength, name)
    return add_clean_manufacturer_name(with_names, F.col("manufacturer"))


def to_silver_columns(df: DataFrame) -> DataFrame:
    """Map one cleaned source onto the shared silver schema, keeping the raw value beside each
    cleaned one so anything can be checked against what the document actually printed."""
    is_spurious = F.col("source_dataset") == SPURIOUS
    has = set(df.columns)

    def column(name: str) -> Column:
        return F.col(name) if name in has else F.lit(None).cast("string")

    return df.select(
        F.col("source_dataset"),
        F.col("source_key"),
        F.col("source_sha256"),
        F.col("source_url"),
        column("page").cast("int").alias("page"),  # portal rows have no page
        F.col("row_index").cast("int").alias("row_index"),
        F.col("alert_month"),
        F.col("extraction_method"),
        F.col("batch_no"),
        # Every `_raw` column is keep_raw()'s snapshot, taken before whitespace cleaning and
        # before fix_portal_batch corrected those 9 batch numbers and dates.
        F.col("batch_no_raw"),
        F.col("mfg_date_raw"),
        F.col("expiry_date_raw"),
        F.col("mfg_date_parsed").alias("mfg_date"),
        F.col("expiry_date_parsed").alias("expiry_date"),
        F.col("dates_valid"),
        F.col("product_name_raw"),
        F.col("split_generic_name").alias("generic_name"),
        F.col("split_brand_name").alias("brand_name"),
        F.col("dosage_form"),
        F.col("strengths"),
        F.col("manufacturer_raw"),
        # On a spurious row the name belongs to the fake pack, not to a maker: keep it only as
        # name_on_pack, and leave every manufacturer column empty so nothing attributes it.
        F.when(~is_spurious, F.col("manufacturer_name")).alias("manufacturer_name"),
        F.when(~is_spurious, F.col("manufacturer_address")).alias("manufacturer_address"),
        is_spurious.alias("is_spurious"),
        F.when(is_spurious, F.col("manufacturer_name")).alias("name_on_pack"),
        F.col("failure_reason"),
        F.col("reported_by"),
        column("remarks").alias("remarks"),
        column("firm_reply").alias("firm_reply"),
    )


def build_silver(pdf: DataFrame, portal: DataFrame) -> DataFrame:
    """Both bronze datasets, cleaned and mapped onto one silver table.

    The manufacturer clustering runs LAST and across both sources at once, so a company written
    one way in a PDF and another way in the portal lands on a single canonical name.
    """
    rows = to_silver_columns(clean_shared(clean_pdf(pdf))).unionByName(
        to_silver_columns(clean_shared(clean_portal(portal)))
    )
    clustered = add_canonical_manufacturer(rows, F.col("manufacturer_name"))
    return clustered.select(SILVER_COLUMNS)


def main() -> None:
    import argparse

    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    parser = argparse.ArgumentParser(description="Build the silver table from bronze.")
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = parser.parse_args()

    spark = spark_session("build-silver")
    try:
        silver = build_silver(read_bronze(spark, PDF), read_bronze(spark, PORTAL)).cache()
        total = silver.count()
        spurious = silver.where("is_spurious").count()
        print(f"{total} silver rows ({spurious} spurious reports)\n")

        filled = [
            ("mfg_date parsed", "mfg_date is not null"),
            ("expiry_date parsed", "expiry_date is not null"),
            ("dosage_form", "dosage_form is not null"),
            ("at least one strength", "size(strengths) > 0"),
            ("brand/generic split", "generic_name is not null"),
            ("manufacturer named", "manufacturer_canonical is not null"),
        ]
        for label, condition in filled:
            n = silver.where(condition).count()
            print(f"  {label:24} {n:5} ({n / total:.1%})")

        makers = silver.where("manufacturer_canonical is not null")
        distinct_makers = makers.select("manufacturer_canonical").distinct().count()
        print(f"\n  distinct manufacturers: {distinct_makers}")
        attributed = silver.where("is_spurious and manufacturer_canonical is not null").count()
        print(f"  spurious rows attributed to a manufacturer: {attributed} (must be 0)")
        print("\n  names kept from fake packs (not attributed to anyone):")
        for row in silver.where("is_spurious and name_on_pack is not null").select(
            "name_on_pack"
        ).distinct().limit(8).collect():  # fmt: skip
            print(f"    {row['name_on_pack'][:72]!r}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return
        silver.write.mode("overwrite").partitionBy("source_dataset", "alert_month").parquet(SILVER)
        print(f"\nwritten to {SILVER}")
        print(f"read back: {spark.read.parquet(SILVER).count()} rows")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
