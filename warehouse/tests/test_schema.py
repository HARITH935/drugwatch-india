"""The staging table's shape: what the SQL says, and what it refuses to say."""

from drugwatch_warehouse import schema


def test_every_column_has_a_postgres_type():
    assert schema.COLUMNS, "the staging table cannot be empty"
    assert all(pg_type for pg_type in schema.COLUMNS.values())


def test_create_table_names_every_column_and_the_load_stamp():
    sql = schema.create_table_sql()
    for name, pg_type in schema.COLUMNS.items():
        assert f"{name} {pg_type}" in sql
    assert f"{schema.LOAD_STAMP} timestamptz NOT NULL DEFAULT now()" in sql
    assert sql.startswith(f"CREATE TABLE IF NOT EXISTS {schema.QUALIFIED}")


def test_lists_stay_arrays_and_dates_stay_dates():
    # These are the types the whole point of ADR 0011 rests on: silver's types are kept, not
    # flattened to text and cast back later.
    assert schema.COLUMNS["failure_categories"] == "text[]"
    assert schema.COLUMNS["strengths"] == "text[]"
    assert schema.COLUMNS["also_reported_in"] == "text[]"
    assert schema.COLUMNS["mfg_date"] == "date"
    assert schema.COLUMNS["expiry_date"] == "date"
    assert schema.COLUMNS["is_spurious"] == "boolean"


def test_alert_month_is_text_not_a_date():
    # 'YYYY-MM' names a CDSCO alert, not a day. Casting it to a date would invent one.
    assert schema.COLUMNS["alert_month"] == "text"


def test_staging_has_no_constraints():
    # Rules belong in dbt tests, where a failure is a named report on data you can query, not a
    # load-time crash (and Phase 3 already gates silver).
    sql = schema.create_table_sql().lower()
    assert "primary key" not in sql
    assert "not null" not in sql.replace(f"{schema.LOAD_STAMP} timestamptz not null", "")


def test_copy_names_its_columns_in_order():
    sql = schema.copy_sql()
    assert sql.startswith(f"COPY {schema.QUALIFIED} (")
    assert ", ".join(schema.COLUMNS) in sql
    assert "FROM STDIN" in sql
    assert schema.LOAD_STAMP not in sql  # filled by its DEFAULT, never sent
