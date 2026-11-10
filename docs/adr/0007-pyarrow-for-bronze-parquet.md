# ADR 0007 — pyarrow writes the bronze Parquet files

- **Status:** Accepted
- **Date:** 2026-11-09
- **Decided by:** Harith (project owner)
- **Affects:** `extraction/pyproject.toml`, `extraction/src/drugwatch_extraction/bronze.py`

---

## Context

Phase 2 step 6 writes the extracted CDSCO rows to the `bronze` bucket as Parquet (plan §7, §9). Phase 3's
PySpark job reads them. The approved stack (plan §6) has Pandas, but Pandas cannot write Parquet by itself:
`DataFrame.to_parquet()` needs an engine library, and none is in the stack.

The bronze rows need three things from the writer:
- **the same columns in every file**, whichever layout family a PDF has, so Spark reads all files as one table;
- **null kept apart from empty text**: a field a layout doesn't have is null, an empty cell stays `""`;
- **list columns** for `pages`, `warnings` and `confidence_reasons`.

## Options considered

| Option | Trade-off |
|---|---|
| **A. pyarrow, used directly** | One dependency. The schema is declared once in code (types, nullable fields, lists), so every file has identical columns. It is the reference Parquet library for Python and the engine Pandas uses anyway. Large wheel (tens of MB). |
| B. Pandas + pyarrow (`df.to_parquet`) | Pulls in Pandas now as well as pyarrow. Pandas guesses column types from each file's data, so a column that is empty in one file can get a different type in another unless types are fixed by hand. |
| C. Pandas + fastparquet | A smaller, less common engine. Weaker support for list columns; Spark and Arrow tooling are mostly tested against pyarrow. |

## Decision

**Option A: pyarrow, used directly.** Only for the Parquet files; Pandas stays approved for the Phase 3
benchmark and Phase 5 exploration, where it will use this same pyarrow as its engine.

- **Schema:** declared once in `bronze.py`. Provenance columns keep their types (`page` and `row_index`
  are integers; `pages`, `warnings` and `confidence_reasons` are lists). Every row field any layout can
  produce is a text column. A header no vocabulary knows (`other_*`) goes into an `other_fields` map
  instead of adding a column. A record with any other unexpected field is refused, not silently dropped.
- **Layout:** one Parquet file per source PDF, at the PDF's `raw/` key with `.parquet` instead of `.pdf`.
  The file name is still the source PDF's SHA-256, so every bronze file points at the exact bytes it came
  from, and re-running replaces the file instead of adding a copy.

## Consequences

- Phase 3's PySpark job reads `bronze/cdsco-pdf/` as one table with one schema.
- A new field in a family vocabulary needs a column in `bronze.py`; a test fails until it is added.
- **Read Parquet with `bronze.from_parquet()`** (Arrow's in-memory reader, one thread), not `pq.read_table()`.
  On macOS the default read starts Arrow thread pools, and the process then sometimes hung at exit waiting for a
  pool worker (extraction report §2.10). A unit test fails if reading starts threads again.
- Portal JSON rows (ADR 0004) go to bronze in a later step, with their own provenance
  (`extraction_method = api`); this ADR covers only the writer library and the PDF rows.
- **Interview angle:** "Bronze has an explicit schema, not one guessed from the data, so null means 'this
  layout has no such column' and an empty string means 'the cell was blank'. Spark gets the same columns
  from every file."
