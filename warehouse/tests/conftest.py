"""Shared fixtures. The integration tests need the local Postgres from docker-compose."""

import os

import pytest


@pytest.fixture
def postgres_connection():
    """A connection to the local Postgres, or skip. Needs `uv run --env-file ../.env`."""
    import psycopg

    from drugwatch_warehouse.load_silver import connection_info

    if not os.environ.get("POSTGRES_PASSWORD"):
        pytest.skip("POSTGRES_PASSWORD not set: run with --env-file ../.env and Postgres up")
    try:
        with psycopg.connect(**connection_info(), connect_timeout=5) as connection:
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no local Postgres: {error}")
