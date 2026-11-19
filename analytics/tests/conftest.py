"""Shared fixtures. The integration tests need the local Postgres with gold loaded."""

import os

import pytest


@pytest.fixture
def gold_available():
    """Skip unless the gold layer is actually reachable."""
    if not os.environ.get("POSTGRES_PASSWORD"):
        pytest.skip("POSTGRES_PASSWORD not set: run with --env-file ../.env and Postgres up")
    import psycopg

    from drugwatch_analytics.gold import connection_info

    try:
        with psycopg.connect(**connection_info()):
            pass
    except psycopg.OperationalError as error:
        pytest.skip(f"no local Postgres: {error}")
