"""Shared fixtures. The integration tests need the local Postgres with gold loaded, or MLflow."""

import os

import pytest


@pytest.fixture
def gold_available():
    """Skip unless the gold layer is actually reachable."""
    if not os.environ.get("POSTGRES_PASSWORD"):
        pytest.skip("POSTGRES_PASSWORD not set: run with --env-file ../.env and Postgres up")
    import psycopg

    from drugwatch_ml.features import connection_info

    try:
        with psycopg.connect(**connection_info()):
            pass
    except psycopg.OperationalError as error:
        pytest.skip(f"no local Postgres: {error}")


@pytest.fixture
def mlflow_available():
    """Skip unless the tracking server answers."""
    import urllib.error
    import urllib.request

    from drugwatch_ml.tracking import tracking_uri

    try:
        urllib.request.urlopen(f"{tracking_uri()}/health", timeout=5)  # noqa: S310 - local URL
    except (urllib.error.URLError, OSError) as error:
        pytest.skip(f"no MLflow server at {tracking_uri()}: {error}")
