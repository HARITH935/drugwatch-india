"""read_bronze.py: reading nested folders of Parquet as one table (local files; RustFS locally)."""

import os

import pytest

from drugwatch_spark.read_bronze import PDF, PORTAL, counts_by, read_bronze, summary


def test_every_file_in_every_sub_folder_is_read(spark, tmp_path):
    # Folders shaped like bronze (dataset/month/file): not key=value partitions.
    for folder, rows in (("central-nsq/2025-06/1", [("B", "TB1"), ("B", "TB2")]),
                         ("spurious/2024-04/2", [("F", "TB3")])):  # fmt: skip
        spark.createDataFrame(rows, ["family", "batch_no"]).write.parquet(str(tmp_path / folder))

    df = read_bronze(spark, str(tmp_path))

    assert sorted(df.columns) == ["batch_no", "family"]  # no extra columns from the folder names
    assert counts_by(df, "family") == {"B": 2, "F": 1}
    assert summary(df, "family")["rows"] == 3


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_spark_reads_both_bronze_datasets_from_rustfs(spark):
    pdf, portal = read_bronze(spark, PDF), read_bronze(spark, PORTAL)

    assert (pdf.count(), summary(pdf, "family")["files"]) == (1317, 44)
    assert counts_by(portal, "source_dataset") == {"nsq": 6956, "spurious": 49}
    assert set(counts_by(portal, "extraction_method")) == {"api"}
