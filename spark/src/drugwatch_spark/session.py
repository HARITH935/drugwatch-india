"""One place that builds the SparkSession every Phase 3 job uses.

local[*]: Spark runs in a JVM started by this Python process, on all CPU cores (no cluster).
S3A: Hadoop's S3 connector, so Spark reads and writes RustFS as s3a://bucket/key (ADR 0008).

    spark = spark_session("read-bronze")            # with RustFS access (needs .env)
    spark = spark_session("tests", s3=False)        # local files only: no connector, no download
"""

import os
from collections.abc import Mapping

from pyspark.sql import SparkSession

HADOOP_VERSION = "3.5.0"  # the Hadoop that PySpark 4.2 is built with; the connector must match it
HADOOP_AWS = (
    f"org.apache.hadoop:hadoop-aws:{HADOOP_VERSION}"  # brings the AWS SDK v2 bundle (686 MB)
)
AWS_SDK_VERSION = "2.35.4"  # the bundle hadoop-aws 3.5.0 declares (prefetch.py downloads it)
DEFAULT_ENDPOINT = "http://localhost:9000"  # same default RawStore.from_env() uses (store.py)
S3A_REQUIRED = ("RUSTFS_ACCESS_KEY", "RUSTFS_SECRET_KEY")


def s3a_conf(env: Mapping[str, str]) -> dict[str, str]:
    """Spark settings for RustFS. Endpoint and keys come from the environment, never from code."""
    missing = [name for name in S3A_REQUIRED if not env.get(name)]
    if missing:
        raise KeyError(f"set {', '.join(missing)} (see .env.example)")
    endpoint = env.get("RUSTFS_ENDPOINT") or DEFAULT_ENDPOINT
    s3a = "spark.hadoop.fs.s3a."  # Spark passes "spark.hadoop.*" settings on to Hadoop
    return {
        "spark.jars.packages": HADOOP_AWS,  # fetched from Maven Central on first use, then cached
        s3a + "endpoint": endpoint,
        s3a + "path.style.access": "true",  # http://host/bucket/key, not bucket.host (ADR 0002)
        s3a + "connection.ssl.enabled": str(endpoint.startswith("https://")).lower(),
        s3a + "endpoint.region": "us-east-1",  # the AWS SDK requires a region; RustFS ignores it
        s3a + "aws.credentials.provider": "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        s3a + "access.key": env["RUSTFS_ACCESS_KEY"],
        s3a + "secret.key": env[
            "RUSTFS_SECRET_KEY"
        ],  # hidden in Spark's logs ("secret" in the name)
    }


def spark_session(
    app: str, *, s3: bool = True, env: Mapping[str, str] = os.environ
) -> SparkSession:
    builder = (
        SparkSession.builder.appName(app)
        .master("local[*]")
        .config("spark.ui.enabled", "false")  # no web UI on port 4040 for short batch jobs
        .config("spark.sql.session.timeZone", "UTC")  # dates mean the same on every machine
        # The default of 200 parallel pieces after a join or group-by suits big clusters; with a
        # few thousand rows most would be empty, which only adds overhead.
        .config("spark.sql.shuffle.partitions", "4")
    )
    if s3:
        for key, value in s3a_conf(env).items():
            builder = builder.config(key, value)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")  # keep Spark's own INFO lines out of the output
    return spark


def hadoop_version(spark: SparkSession) -> str:
    """The Hadoop version this Spark is built with (asked from the JVM)."""
    return spark.sparkContext._jvm.org.apache.hadoop.util.VersionInfo.getVersion()
