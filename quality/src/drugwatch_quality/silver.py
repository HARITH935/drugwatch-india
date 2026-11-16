"""Read the silver table out of RustFS, for the quality checks to run against.

Silver is Parquet partitioned by `source_dataset` and `alert_month` (build_silver.py writes it
that way), which means the two partition columns are not inside the files at all - they are
encoded in the directory names, Hive-style (`source_dataset=nsq/alert_month=2025-06/...`).
`partitioning="hive"` is what puts them back as real columns.

This reads with **pyarrow**, not Spark. Silver is ~7,000 rows: Spark would mean starting a JVM and
the 686 MB AWS SDK bundle (ADR 0008) to read a file pandas handles in a second. pyarrow has its
own S3 client, so RustFS needs no extra library - just the same endpoint and keys everything else
uses (ADR 0002: path-style addressing, which pyarrow does by default against a custom endpoint).

    df = read_silver()                      # the whole table, from the environment's RustFS
    df = read_dataset(path, filesystem)     # any Parquet dataset (used by the tests, on local disk)
"""

import os
from collections.abc import Mapping

import pandas as pd
import pyarrow.dataset as ds
from pyarrow import fs

SILVER_PATH = "silver/nsq"  # bucket + prefix, as pyarrow's S3 client addresses it
DEFAULT_ENDPOINT = "http://localhost:9000"  # same default as RawStore.from_env() and session.py
REQUIRED = ("RUSTFS_ACCESS_KEY", "RUSTFS_SECRET_KEY")
# Written as partition directories, so they come back dictionary-encoded and need converting.
PARTITION_COLUMNS = ("source_dataset", "alert_month")


def endpoint_parts(endpoint: str) -> tuple[str, str]:
    """`("http", "localhost:9000")` from `"http://localhost:9000"`.

    pyarrow wants the scheme and the host:port as separate arguments. Splitting carelessly is
    quietly broken rather than noisy: `"localhost:9000"` with no scheme would partition into
    scheme `"localhost:9000"` and an empty host, and the client would just fail to connect.
    """
    scheme, separator, host = endpoint.partition("://")
    if not separator or not host:
        raise ValueError(f"RUSTFS_ENDPOINT needs a scheme, e.g. http://host:9000, got {endpoint!r}")
    return scheme, host


def s3_filesystem(env: Mapping[str, str] = os.environ) -> fs.S3FileSystem:
    """pyarrow's S3 client, pointed at RustFS. Keys come from the environment, never from code."""
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        raise KeyError(f"set {', '.join(missing)} (see .env.example)")
    scheme, host = endpoint_parts(env.get("RUSTFS_ENDPOINT") or DEFAULT_ENDPOINT)
    return fs.S3FileSystem(
        access_key=env["RUSTFS_ACCESS_KEY"],
        secret_key=env["RUSTFS_SECRET_KEY"],
        endpoint_override=host,  # host:port only; the scheme is passed separately
        scheme=scheme,
        region="us-east-1",  # RustFS ignores it, but the S3 client insists on one
    )


def read_dataset(path: str, filesystem: fs.FileSystem) -> pd.DataFrame:
    """A Hive-partitioned Parquet dataset as a DataFrame, partition columns included."""
    dataset = ds.dataset(path, filesystem=filesystem, format="parquet", partitioning="hive")
    frame = dataset.to_table().to_pandas()
    # Partition values arrive dictionary-encoded (pandas categoricals). Plain strings keep the
    # checks simple: a categorical compares and serialises differently in the GE report.
    for column in PARTITION_COLUMNS:
        if column in frame.columns and isinstance(frame[column].dtype, pd.CategoricalDtype):
            frame[column] = frame[column].astype("string")
    return frame


def read_silver(env: Mapping[str, str] = os.environ) -> pd.DataFrame:
    """The whole silver table from RustFS."""
    return read_dataset(SILVER_PATH, s3_filesystem(env))


def main() -> None:
    """Print what silver holds right now (a smoke test for the connection and the schema).

    Run (from quality/, RustFS up):
        uv run --env-file ../.env python -m drugwatch_quality.silver
    """
    frame = read_silver()
    print(f"{len(frame)} rows, {len(frame.columns)} columns\n")
    print("columns:")
    for name, dtype in frame.dtypes.items():
        filled = frame[name].notna().sum()
        print(f"  {name:22} {str(dtype):16} {filled:5} filled ({filled / len(frame):.0%})")


if __name__ == "__main__":
    main()
