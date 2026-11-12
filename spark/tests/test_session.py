"""session.py: the S3A settings, and the connector matching Spark's own Hadoop version."""

import pytest

from drugwatch_spark.session import DEFAULT_ENDPOINT, HADOOP_VERSION, hadoop_version, s3a_conf

ENV = {
    "RUSTFS_ENDPOINT": "http://localhost:9000",
    "RUSTFS_ACCESS_KEY": "ak",
    "RUSTFS_SECRET_KEY": "sk",
}


def test_rustfs_settings_come_from_the_environment():
    conf = s3a_conf(ENV)

    assert conf["spark.hadoop.fs.s3a.endpoint"] == "http://localhost:9000"
    assert conf["spark.hadoop.fs.s3a.path.style.access"] == "true"  # ADR 0002
    assert conf["spark.hadoop.fs.s3a.connection.ssl.enabled"] == "false"  # plain http locally
    assert (conf["spark.hadoop.fs.s3a.access.key"], conf["spark.hadoop.fs.s3a.secret.key"]) == (
        "ak",
        "sk",
    )
    assert conf["spark.jars.packages"] == f"org.apache.hadoop:hadoop-aws:{HADOOP_VERSION}"


def test_https_endpoints_use_tls():
    conf = s3a_conf(ENV | {"RUSTFS_ENDPOINT": "https://lake.example"})

    assert conf["spark.hadoop.fs.s3a.connection.ssl.enabled"] == "true"


def test_a_missing_endpoint_defaults_like_rawstore_from_env():
    # ingestion/.../store.py's RawStore.from_env() defaults the same way; .env doesn't set this.
    conf = s3a_conf({k: v for k, v in ENV.items() if k != "RUSTFS_ENDPOINT"})

    assert conf["spark.hadoop.fs.s3a.endpoint"] == DEFAULT_ENDPOINT


def test_missing_credentials_stop_with_a_clear_message():
    with pytest.raises(KeyError, match="RUSTFS_SECRET_KEY"):
        s3a_conf(ENV | {"RUSTFS_SECRET_KEY": ""})


def test_the_connector_matches_the_hadoop_spark_is_built_with(spark):
    # A PySpark upgrade that moves Hadoop must move hadoop-aws too (ADR 0008).
    assert hadoop_version(spark) == HADOOP_VERSION
