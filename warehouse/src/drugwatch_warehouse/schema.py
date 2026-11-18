"""The shape of the Postgres staging table: one column per silver column, same meaning.

`staging` is a landing schema, not the gold layer. Its job is to hold silver *as it is* so dbt
can do the renaming, casting and reshaping in SQL that is version-controlled and tested
(Phase 4 steps 2-4). So nothing here cleans, renames or drops anything.

Two things it does NOT do, on purpose:

- **No constraints.** No primary key, no NOT NULL. A constraint here would reject a row at load
  time, which hides the problem in a stack trace; the same rule written as a dbt test reports it
  as a named failing test against data that is already in the database and can be looked at.
  De-duplication already happened in Phase 3 (ADR 0010) and the Great Expectations suite already
  gates silver, so a constraint here would be the third guard on the same rule.

- **No invented types.** Where silver has a real type, the column keeps it: dates stay `date`,
  `is_spurious` stays `boolean`, the three list columns stay `text[]`. Loading everything as text
  and casting later would be throwing away type information Parquet already carries correctly.

The column list is written out in full rather than derived from the DataFrame, so that a silver
schema change (Phase 3 gains or renames a column) fails this load loudly instead of quietly
loading 31 of 32 columns - same reasoning as the restated vocabularies in the GE suite.
"""

SCHEMA = "staging"
TABLE = "silver_nsq"
QUALIFIED = f"{SCHEMA}.{TABLE}"

# column -> Postgres type. Order is the order COPY sends them in; it is fixed here and never
# taken from the DataFrame, because pyarrow appends the partition columns wherever it likes.
COLUMNS: dict[str, str] = {
    # provenance: which document, which page, which row (CLAUDE.md Section 5)
    "source_dataset": "text",
    "source_key": "text",
    "source_sha256": "text",
    "source_url": "text",
    "page": "integer",  # PDF rows only; portal rows have no page, so it is nullable
    "row_index": "integer",
    "alert_month": "text",  # 'YYYY-MM' as published, not a date: it names a CDSCO alert, not a day
    "extraction_method": "text",  # rule / llm / api (ADR 0004)
    "also_reported_in": "text[]",  # other documents that published the same finding (ADR 0010)
    # the batch this alert is about
    "batch_no": "text",
    "batch_no_raw": "text",
    # dates: as printed, and as parsed (null where no proven-safe format fits)
    "mfg_date_raw": "text",
    "expiry_date_raw": "text",
    "mfg_date": "date",
    "expiry_date": "date",
    "dates_valid": "boolean",  # nullable on purpose: unknown is not the same as invalid
    # the medicine
    "product_name_raw": "text",
    "generic_name": "text",
    "brand_name": "text",
    "dosage_form": "text",
    "strengths": "text[]",  # every strength the name prints, as printed
    # who made it - or, for a spurious report, the name printed on the fake pack
    "manufacturer_raw": "text",
    "manufacturer_name": "text",
    "manufacturer_address": "text",
    "manufacturer_canonical": "text",  # after entity resolution (Phase 3 step 5)
    "is_spurious": "boolean",
    "name_on_pack": "text",
    # what was wrong
    "failure_reason": "text",
    "failure_categories": "text[]",  # a list: 22.6% of rows name more than one failed test
    "reported_by": "text",
    "remarks": "text",
    "firm_reply": "text",
}

# Not from silver: when this load ran. dbt and Airflow both want to know how fresh gold is, and
# a DEFAULT means COPY never has to send the value.
LOAD_STAMP = "loaded_at"


def create_schema_sql() -> str:
    return f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"


def create_table_sql() -> str:
    """CREATE TABLE IF NOT EXISTS for the staging table, one column per line."""
    columns = [f"    {name} {pg_type}" for name, pg_type in COLUMNS.items()]
    columns.append(f"    {LOAD_STAMP} timestamptz NOT NULL DEFAULT now()")
    body = ",\n".join(columns)
    return f"CREATE TABLE IF NOT EXISTS {QUALIFIED} (\n{body}\n)"


def copy_sql() -> str:
    """COPY ... FROM STDIN: Postgres' bulk path, one stream instead of one INSERT per row.

    The column list is named explicitly so the load does not depend on the table's column order
    (which would change the day someone adds a column in the middle)."""
    names = ", ".join(COLUMNS)
    return f"COPY {QUALIFIED} ({names}) FROM STDIN"
