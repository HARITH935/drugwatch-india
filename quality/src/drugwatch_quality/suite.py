r"""Phase 3 step 8: the Great Expectations suite that silver has to pass.

Every other Phase 3 module printed a report for a person to read once. This is the check that
runs on every build and **fails** when silver is wrong - what Phase 5's Airflow DAG gates on
before anything is published, and what catches a CDSCO format change that quietly breaks a parser.

**The thresholds are measured, not guessed** (real silver, 7,128 rows, 2026-11-16). Where real
data legitimately breaks a rule, the expectation says so with `mostly=` and the reason is written
down, rather than the rule being dropped:

- **`dates_valid` is False on 17 rows** - genuine CDSCO typos found in step 3 (one batch prints a
  manufacturing date 16 years after its own expiry). Those are facts about the source, so the
  expectation allows 99%: it still fires if a parser starts inverting dates wholesale.
- **7 of 7,128 batch numbers contain no letter or digit at all** (2 blank, the rest punctuation
  like `"--"`). CDSCO printed them that way; the check allows 99.9%.
- **22 batch numbers carry mojibake** (`"T?18909"`, where a dash was mangled) and **62 contain a
  line break**, so there is deliberately NO format regex on batch_no beyond "has some text in it".
  A stricter rule would fail on real, correct rows.

**The vocabularies below are restated on purpose, not imported from `drugwatch_spark`.** A check
that imports the thing it is checking only proves the code agrees with itself. Stating the
expected values independently means that if someone edits the category list in the pipeline, this
suite fails and a person decides which side is right. That is the whole point of a quality gate.

Run (from quality/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_quality.suite        # exits 1 if silver fails
"""

import great_expectations as gx
import pandas as pd
from great_expectations.core.validation_definition import ValidationDefinition

# What build_silver is expected to produce. Restated here on purpose (see the docstring).
EXPECTED_CATEGORIES = frozenset(
    {
        "Assay", "Description", "Disintegration", "Dissolution", "Identification", "Labelling",
        "Other", "Particulate", "Physical", "Related substances", "Spurious", "Sterility",
        "Uniformity", "Water", "pH",
    }
)  # fmt: skip
# portal JSON / PDF parser. NOT "llm": Phase 10's fallback was built, audited on the real archive
# and not integrated (ADR 0019, amendment 4), so an `llm` row reaching silver is a failure.
EXPECTED_METHODS = ["api", "rule"]
EXPECTED_DATASETS = ["central-nsq", "state-nsq", "nsq", "spurious", "combined"]
# Silver only grows, by roughly 100-300 rows a month. Below the floor means data was lost; above
# the ceiling, within this phase, means de-duplication regressed.
ROW_COUNT = (7_000, 15_000)
PLAUSIBLE_YEARS = (1990, 2049)  # the same range parse_dates.py enforces on every parsed date
NEVER_NULL = (
    "source_key", "source_sha256", "source_url", "extraction_method", "source_dataset",
    "alert_month", "row_index", "batch_no", "product_name_raw", "manufacturer_raw",
    "is_spurious", "failure_categories", "also_reported_in",
)  # fmt: skip


def prepared(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the few plain columns GE cannot express over nested values.

    `failure_categories` and `strengths` are lists inside each cell, and `mfg_date` holds date
    objects; expectations work on flat, comparable values, so the facts being checked are pulled
    out into their own columns first. Nothing here changes silver - it is a view for validating.
    """
    checked = frame.copy()
    checked["category_count"] = checked["failure_categories"].map(len)
    checked["unknown_categories"] = checked["failure_categories"].map(
        lambda values: sum(1 for value in values if value not in EXPECTED_CATEGORIES)
    )
    for column in ("mfg_date", "expiry_date"):
        checked[f"{column}_year"] = checked[column].map(
            lambda value: None if pd.isna(value) else value.year
        )
    return checked


def expectations() -> list[gx.expectations.Expectation]:
    """Every rule silver must satisfy, in the order they are reported."""
    checks: list[gx.expectations.Expectation] = [
        # --- the table as a whole -------------------------------------------------------
        gx.expectations.ExpectTableRowCountToBeBetween(
            min_value=ROW_COUNT[0], max_value=ROW_COUNT[1]
        ),
        # One row per finding (step 7). This is the proof that de-duplication did not leave a
        # row twice, and that nothing downstream double-counts a batch.
        gx.expectations.ExpectCompoundColumnsToBeUnique(
            column_list=["source_key", "page", "row_index"]
        ),
        # --- provenance: every row traceable to its document (CLAUDE.md Section 5) --------
        *(gx.expectations.ExpectColumnValuesToNotBeNull(column=name) for name in NEVER_NULL),
        gx.expectations.ExpectColumnValuesToMatchRegex(
            column="source_sha256", regex=r"^[0-9a-f]{64}$"
        ),
        gx.expectations.ExpectColumnValuesToMatchRegex(
            column="alert_month", regex=r"^[0-9]{4}-(0[1-9]|1[0-2])$"
        ),
        # --- the vocabularies ------------------------------------------------------------
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="extraction_method", value_set=EXPECTED_METHODS
        ),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="source_dataset", value_set=EXPECTED_DATASETS
        ),
        # Every failure category is one this project defined (ADR 0009), and every row has at
        # least one - an unrecognised reason becomes "Other", never an empty list.
        gx.expectations.ExpectColumnMaxToBeBetween(column="unknown_categories", max_value=0),
        gx.expectations.ExpectColumnMinToBeBetween(column="category_count", min_value=1),
        # --- the batch, the thing a visitor actually searches for -------------------------
        # No format rule beyond "has some text": 22 real batch numbers carry mojibake and 62
        # contain a line break, and they are correct rows. 7 of 7,128 have no letter or digit.
        gx.expectations.ExpectColumnValuesToMatchRegex(
            column="batch_no", regex=r"[A-Za-z0-9]", mostly=0.999
        ),
        # --- dates ------------------------------------------------------------------------
        *(
            gx.expectations.ExpectColumnValuesToBeBetween(
                column=f"{column}_year",
                min_value=PLAUSIBLE_YEARS[0],
                max_value=PLAUSIBLE_YEARS[1],
            )
            for column in ("mfg_date", "expiry_date")
        ),
        # 17 real rows print a manufacturing date on or after the expiry date - CDSCO typos,
        # kept exactly as printed and flagged. 99% still catches a parser inverting dates.
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="dates_valid", value_set=[True], mostly=0.99
        ),
        # --- the spurious rule, in code (CLAUDE.md Section 6) -----------------------------
        # A spurious alert names the company printed on a FAKE pack. Attributing it would accuse
        # a counterfeiting victim, so every manufacturer column must be empty on those rows...
        *(
            gx.expectations.ExpectColumnValuesToBeNull(
                column=column, row_condition="is_spurious==True", condition_parser="pandas"
            )
            for column in ("manufacturer_canonical", "manufacturer_name", "manufacturer_address")
        ),
        # ...and name_on_pack must never appear on a row that is not a spurious report.
        gx.expectations.ExpectColumnValuesToBeNull(
            column="name_on_pack", row_condition="is_spurious==False", condition_parser="pandas"
        ),
    ]
    return checks


def validation_definition(context: gx.data_context.AbstractDataContext) -> ValidationDefinition:
    """Wire the suite to a pandas batch, so `.run(batch_parameters=...)` can validate a frame."""
    asset = context.data_sources.add_pandas("silver").add_dataframe_asset("nsq")
    batch = asset.add_batch_definition_whole_dataframe("whole_table")
    suite = context.suites.add(gx.ExpectationSuite(name="silver-nsq"))
    for expectation in expectations():
        suite.add_expectation(expectation)
    return context.validation_definitions.add(
        gx.ValidationDefinition(data=batch, suite=suite, name="silver-nsq-validation")
    )


def validate(frame: pd.DataFrame):
    """Run every expectation against a silver-shaped DataFrame and return GE's result."""
    context = gx.get_context(mode="ephemeral")
    return validation_definition(context).run(batch_parameters={"dataframe": prepared(frame)})


def describe(result) -> list[str]:
    """One readable line per expectation, failures first."""
    lines = []
    for outcome in sorted(result.results, key=lambda r: r.success):
        config = outcome.expectation_config
        column = config.kwargs.get("column") or ",".join(config.kwargs.get("column_list", []))
        where = config.kwargs.get("row_condition")
        unexpected = outcome.result.get("unexpected_count")
        detail = f" {unexpected} bad" if unexpected else ""
        scope = f" where {where['pass_through_filter']}" if isinstance(where, dict) else ""
        mark = "ok  " if outcome.success else "FAIL"
        lines.append(f"  {mark} {config.type.removeprefix('expect_'):42} {column}{scope}{detail}")
    return lines


def main() -> None:
    """Validate the real silver table; exit 1 if anything fails, for Airflow to act on."""
    import sys
    import warnings

    from drugwatch_quality.silver import read_silver

    warnings.filterwarnings("ignore")  # GE's progress bars and pandas deprecations
    frame = read_silver()
    result = validate(frame)

    stats = result.statistics
    print(f"\nsilver: {len(frame)} rows")
    print(
        f"{stats['successful_expectations']}/{stats['evaluated_expectations']} expectations passed"
        f" ({stats['success_percent']:.0f}%)\n"
    )
    for line in describe(result):
        print(line)
    print(f"\n{'PASSED' if result.success else 'FAILED'}")
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
