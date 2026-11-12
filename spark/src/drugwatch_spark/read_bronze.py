"""Phase 3 step 1: Spark reads both bronze datasets from RustFS.

    s3a://bronze/cdsco-pdf/      PDF records, one Parquet file per PDF (Phase 2; ADR 0007)
    s3a://bronze/cdsco-portal/   portal records, one Parquet file per month (Phase 3 step 0)

Each dataset has one schema across all its files, so Spark reads a whole folder as one table.

Run (from spark/, RustFS up; the first run downloads the S3A connector, about 700 MB, ADR 0008):
    uv run --env-file ../.env python -m drugwatch_spark.read_bronze
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from drugwatch_spark.session import spark_session

PDF = "s3a://bronze/cdsco-pdf/"
PORTAL = "s3a://bronze/cdsco-portal/"


def read_bronze(spark: SparkSession, path: str) -> DataFrame:
    """Every Parquet file under `path`, as one DataFrame."""
    # recursiveFileLookup: look in every sub-folder. Our folders (dataset/month/file id) aren't
    # Spark's "key=value" partition folders, so Spark mustn't try to read them as columns.
    return spark.read.option("recursiveFileLookup", "true").parquet(path)


def counts_by(df: DataFrame, column: str) -> dict[str, int]:
    """Rows per value of `column`, as a plain dict (the work stays in Spark; only counts return)."""
    return {row[column]: row["count"] for row in df.groupBy(column).count().collect()}


def summary(df: DataFrame, group: str) -> dict:
    return {
        "rows": df.count(),
        "files": df.select(F.input_file_name()).distinct().count(),  # which file each row came from
        "columns": len(df.columns),
        f"by {group}": dict(sorted(counts_by(df, group).items())),
    }


def main() -> None:
    spark = spark_session("read-bronze")
    try:
        for name, path, group in (("PDF", PDF, "family"), ("portal", PORTAL, "source_dataset")):
            df = read_bronze(spark, path)
            print(f"{name} bronze ({path}): {summary(df, group)}")
    finally:
        spark.stop()  # shuts the JVM down cleanly


if __name__ == "__main__":
    main()
