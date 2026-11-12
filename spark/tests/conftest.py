"""One Spark session for the whole test run: starting the JVM takes a few seconds, and Spark allows
one session per process (a second spark_session() call would silently return the first).

With RustFS credentials in the environment (local runs with --env-file), the session can also read
the lake. Without them (CI), it reads local files only, and the S3 connector is never downloaded.
"""

import os

import pytest

from drugwatch_spark.session import spark_session


@pytest.fixture(scope="session")
def spark():
    session = spark_session("tests", s3="RUSTFS_ACCESS_KEY" in os.environ)
    yield session
    session.stop()
