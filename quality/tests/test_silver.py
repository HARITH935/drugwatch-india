"""silver.py: reading a Hive-partitioned Parquet dataset, and the RustFS credentials."""

import os

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pyarrow import fs

from drugwatch_quality.silver import (
    endpoint_parts,
    read_dataset,
    read_silver,
    s3_filesystem,
)

SILVER_COLUMNS = {  # a few columns the suite depends on; the real table has 32
    "source_key",
    "batch_no",
    "alert_month",
    "source_dataset",
    "failure_categories",
    "is_spurious",
}


@pytest.fixture
def partitioned(tmp_path):
    """A tiny dataset laid out the way build_silver writes silver."""
    table = pa.table(
        {
            "source_key": ["a", "b", "c"],
            "batch_no": ["TB-1", "TB-2", "TB-3"],
            "source_dataset": ["nsq", "nsq", "state-nsq"],
            "alert_month": ["2025-05", "2025-06", "2025-06"],
        }
    )
    pq.write_to_dataset(
        table, str(tmp_path / "nsq"), partition_cols=["source_dataset", "alert_month"]
    )
    return str(tmp_path / "nsq")


def test_the_partition_columns_come_back_as_columns(partitioned):
    # They are not stored inside the files at all - only in the directory names - so without
    # Hive partitioning both would simply be missing from the frame.
    frame = read_dataset(partitioned, fs.LocalFileSystem())

    assert len(frame) == 3
    assert {"source_dataset", "alert_month"} <= set(frame.columns)
    assert sorted(frame["alert_month"].unique()) == ["2025-05", "2025-06"]


def test_partition_values_are_plain_strings_not_categoricals(partitioned):
    # pyarrow dictionary-encodes partition values; a categorical compares and serialises
    # differently inside GE's report, so the reader converts them.
    frame = read_dataset(partitioned, fs.LocalFileSystem())

    for column in ("source_dataset", "alert_month"):
        assert not isinstance(frame[column].dtype, pd.CategoricalDtype)
        assert frame[column].iloc[0] == frame[column].iloc[0].strip()  # real string behaviour


def test_credentials_must_come_from_the_environment():
    with pytest.raises(KeyError, match="RUSTFS_ACCESS_KEY"):
        s3_filesystem({})


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://localhost:9000", ("http", "localhost:9000")),
        ("https://rustfs.example:443", ("https", "rustfs.example:443")),
    ],
)
def test_the_endpoint_scheme_is_split_from_the_host(endpoint, expected):
    # pyarrow wants host:port in endpoint_override and the scheme separately.
    assert endpoint_parts(endpoint) == expected


@pytest.mark.parametrize("endpoint", ["localhost:9000", "http://", "rustfs"])
def test_an_endpoint_without_a_scheme_is_rejected_loudly(endpoint):
    # Otherwise "localhost:9000" splits into scheme "localhost:9000" and an empty host, and the
    # client simply fails to connect with nothing explaining why.
    with pytest.raises(ValueError, match="needs a scheme"):
        endpoint_parts(endpoint)


def test_the_client_is_built_from_the_environment():
    filesystem = s3_filesystem(
        {
            "RUSTFS_ACCESS_KEY": "key",
            "RUSTFS_SECRET_KEY": "secret",
            "RUSTFS_ENDPOINT": "http://localhost:9000",
        }
    )

    assert isinstance(filesystem, fs.S3FileSystem)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RUSTFS_ACCESS_KEY"), reason="needs local RustFS with real silver/"
)
def test_the_real_silver_table_reads():
    frame = read_silver()

    assert len(frame) > 1000
    assert SILVER_COLUMNS <= set(frame.columns)
    assert frame["alert_month"].notna().all()  # step 7 removed the only rows missing it
