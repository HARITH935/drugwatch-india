"""The gold reader: its settings, and the read-only guarantee it claims."""

import pytest

from drugwatch_analytics.gold import connection_info, gold_tables, query


def test_the_password_is_never_defaulted():
    with pytest.raises(KeyError, match="POSTGRES_PASSWORD"):
        connection_info({"POSTGRES_HOST": "localhost"})


def test_defaults_match_docker_compose():
    info = connection_info({"POSTGRES_PASSWORD": "secret"})
    assert (info["host"], info["port"]) == ("localhost", 5433)
    assert (info["user"], info["dbname"]) == ("drugwatch", "drugwatch")


def test_the_environment_wins_over_the_defaults():
    info = connection_info(
        {"POSTGRES_PASSWORD": "x", "POSTGRES_HOST": "postgres", "POSTGRES_PORT": "5432"}
    )
    assert (info["host"], info["port"]) == ("postgres", 5432)


@pytest.mark.integration
def test_a_select_comes_back_as_a_dataframe(gold_available):
    frame = query("SELECT count(*) AS findings FROM gold.fact_nsq_sample")
    assert list(frame.columns) == ["findings"]
    assert frame.iloc[0]["findings"] > 0


@pytest.mark.integration
def test_the_connection_really_is_read_only(gold_available):
    """The claim in the module docstring, checked against the database rather than trusted.

    A notebook must not be able to change the warehouse, even by accident.
    """
    import psycopg

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        query("CREATE TABLE gold.should_not_exist (x int)")


@pytest.mark.integration
def test_gold_tables_lists_the_star_schema(gold_available):
    tables = gold_tables()
    names = set(tables["table_name"])
    assert {"fact_nsq_sample", "dim_drug", "dim_manufacturer", "dim_state", "dim_date"} <= names
    assert (tables["rows"] > 0).all()
