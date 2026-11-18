"""The loader: value conversion, the guards, and one real COPY against the local Postgres."""

import datetime as dt

import pandas as pd
import pytest

from drugwatch_warehouse import schema
from drugwatch_warehouse.load_silver import (
    check_columns,
    connection_info,
    load,
    rows_for_copy,
    to_postgres_value,
)


def silver_like(**overrides) -> pd.DataFrame:
    """One row with every silver column, so tests can change just the field they are about."""
    row = dict.fromkeys(schema.COLUMNS)
    row.update(
        source_dataset="nsq",
        source_key="raw/cdsco-portal/nsq/2025-06.json",
        source_sha256="a" * 64,
        source_url="https://example.invalid/alert.pdf",
        page=None,
        row_index=0,
        alert_month="2025-06",
        extraction_method="api",
        also_reported_in=[],
        batch_no="ABC123",
        batch_no_raw="ABC 123",
        mfg_date=dt.date(2024, 1, 1),
        expiry_date=dt.date(2026, 1, 1),
        dates_valid=True,
        product_name_raw="Paracetamol Tablets IP 500 mg",
        strengths=["500 mg"],
        manufacturer_raw="Example Pharma Pvt. Ltd., Baddi",
        manufacturer_name="Example Pharma Private Limited",
        manufacturer_canonical="Example Pharma Private Limited",
        is_spurious=False,
        failure_reason="Assay",
        failure_categories=["Assay"],
    )
    row.update(overrides)
    return pd.DataFrame([row])


# --- converting one value -------------------------------------------------------------------


@pytest.mark.parametrize("missing", [float("nan"), pd.NaT, pd.NA, None])
def test_every_spelling_of_missing_becomes_none(missing):
    assert to_postgres_value(missing, "text") is None


def test_a_float_page_becomes_an_integer():
    # page is float64 in pandas only because 97% of rows are NULL; Postgres wants an int.
    assert to_postgres_value(5.0, "integer") == 5
    assert isinstance(to_postgres_value(5.0, "integer"), int)


def test_a_float_stays_a_float_for_a_non_integer_column():
    assert to_postgres_value(5.0, "double precision") == 5.0


def test_numpy_values_become_plain_python():
    frame = pd.DataFrame({"n": [1], "flag": [True]})
    value = frame["n"].iloc[0]
    assert hasattr(value, "tolist"), "this test is pointless if pandas stopped using numpy"
    assert to_postgres_value(value, "integer") == 1
    assert to_postgres_value(frame["flag"].iloc[0], "boolean") is True


def test_lists_survive_as_lists():
    assert to_postgres_value(["Assay", "Dissolution"], "text[]") == ["Assay", "Dissolution"]
    assert to_postgres_value([], "text[]") == []


def test_an_empty_list_is_not_mistaken_for_missing():
    # The order matters: pd.isna([]) returns an empty array, not False, so the array branch has
    # to come first or an empty list would become NULL.
    assert to_postgres_value([], "text[]") == []


# --- the guards -----------------------------------------------------------------------------


def test_a_missing_column_is_refused():
    frame = silver_like().drop(columns=["batch_no"])
    with pytest.raises(ValueError, match="batch_no"):
        check_columns(frame)


def test_an_unexpected_column_is_refused():
    frame = silver_like().assign(new_field_from_phase_3="x")
    with pytest.raises(ValueError, match="new_field_from_phase_3"):
        check_columns(frame)


def test_an_empty_silver_never_wipes_the_table():
    frame = silver_like().iloc[0:0]
    with pytest.raises(ValueError, match="empty"):
        load(frame, connection=None)  # raises before it touches the connection


def test_rows_are_sent_in_the_schemas_column_order():
    # Even when the DataFrame's own order is different, which pyarrow's partition columns make
    # true for real silver.
    frame = silver_like()
    shuffled = frame[list(reversed(frame.columns))]
    (row,) = rows_for_copy(shuffled)
    assert len(row) == len(schema.COLUMNS)
    assert row[list(schema.COLUMNS).index("batch_no")] == "ABC123"
    assert row[list(schema.COLUMNS).index("alert_month")] == "2025-06"


# --- connection settings --------------------------------------------------------------------


def test_the_password_is_never_defaulted():
    with pytest.raises(KeyError, match="POSTGRES_PASSWORD"):
        connection_info({"POSTGRES_HOST": "localhost"})


def test_defaults_match_docker_compose():
    info = connection_info({"POSTGRES_PASSWORD": "secret"})
    assert (info["host"], info["port"]) == ("localhost", 5433)
    assert (info["user"], info["dbname"]) == ("drugwatch", "drugwatch")


def test_the_environment_wins_over_the_defaults():
    info = connection_info(
        {"POSTGRES_PASSWORD": "secret", "POSTGRES_HOST": "postgres", "POSTGRES_PORT": "5432"}
    )
    assert (info["host"], info["port"]) == ("postgres", 5432)


# --- one real round trip --------------------------------------------------------------------


@pytest.mark.integration
def test_a_row_survives_copy_into_a_real_postgres(postgres_connection, monkeypatch):
    """COPY the row in and read it back: this is what proves the type adaptation works.

    Loads into its own table, not the real staging one, so running the tests never disturbs
    whatever the last real load left behind."""
    monkeypatch.setattr(schema, "QUALIFIED", f"{schema.SCHEMA}.silver_nsq_pytest")
    frame = silver_like(page=3.0, also_reported_in=["raw/a.pdf", "raw/b.pdf"])
    try:
        assert load(frame, postgres_connection) == 1
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                f"SELECT batch_no, page, mfg_date, is_spurious, failure_categories, "  # noqa: S608
                f"also_reported_in, strengths, dates_valid, remarks, loaded_at "
                f"FROM {schema.QUALIFIED}"
            )
            (
                batch_no, page, mfg_date, is_spurious,
                categories, also_reported_in, strengths, dates_valid, remarks, loaded_at,
            ) = cursor.fetchone()  # fmt: skip
        assert batch_no == "ABC123"
        assert page == 3  # float64 -> integer
        assert mfg_date == dt.date(2024, 1, 1)  # a real date, not text
        assert is_spurious is False
        assert categories == ["Assay"]  # text[], not a string that looks like a list
        assert also_reported_in == ["raw/a.pdf", "raw/b.pdf"]
        assert strengths == ["500 mg"]
        assert dates_valid is True
        assert remarks is None  # None stayed NULL
        assert loaded_at is not None  # filled by its DEFAULT, never sent by COPY
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {schema.QUALIFIED}")


@pytest.mark.integration
def test_loading_twice_leaves_one_copy(postgres_connection, monkeypatch):
    """Idempotence, which Phase 5's DAG depends on: a re-run replaces, never appends."""
    monkeypatch.setattr(schema, "QUALIFIED", f"{schema.SCHEMA}.silver_nsq_pytest")
    frame = silver_like()
    try:
        load(frame, postgres_connection)
        assert load(frame, postgres_connection) == 1
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {schema.QUALIFIED}")
