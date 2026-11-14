"""deduplicate.py: what counts as one finding, which row wins, and what must never merge.

The rows below mirror real archive cases: a portal row and a PDF row for the same batch, one
maker reusing a batch number across five injections, and placeholder batch numbers.
"""

import pytest
from pyspark.sql.types import (
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from drugwatch_spark.deduplicate import deduplicate

SCHEMA = StructType(
    [
        StructField(name, StringType())
        for name in (
            "source_dataset", "source_key", "source_sha256", "source_url", "alert_month",
            "extraction_method", "batch_no", "product_name_raw", "manufacturer_canonical",
            "name_on_pack", "failure_reason", "remarks", "firm_reply", "mfg_date",
        )
    ]
    + [
        StructField("page", IntegerType()),
        StructField("row_index", IntegerType()),
        StructField("is_spurious", BooleanType()),
    ]
)  # fmt: skip

PORTAL = {
    "source_dataset": "nsq", "source_key": "bronze/cdsco-portal/2025-06", "source_sha256": "aa",
    "source_url": "https://cdscoonline/x", "alert_month": "2025-06", "extraction_method": "api",
    "batch_no": "MER3 294D", "product_name_raw": "Paracetamol Tablets IP 500 mg",
    "manufacturer_canonical": "Test Pharma Limited", "name_on_pack": None,
    "failure_reason": "Dissolution", "remarks": None, "firm_reply": None, "mfg_date": "Nov-2024",
    "page": None, "row_index": 7, "is_spurious": False,
}  # fmt: skip
PDF = {
    **PORTAL,
    "source_dataset": "state-nsq", "source_key": "bronze/cdsco-pdf/state-nsq/2025-06",
    "source_sha256": "bb", "source_url": "https://cdsco.gov.in/x.pdf",
    "extraction_method": "rule", "batch_no": "MER3  294D",
    "failure_reason": "Dissolution", "page": 3, "row_index": 2,
}  # fmt: skip


def rows(spark, *dicts):
    return spark.createDataFrame([tuple(d[f.name] for f in SCHEMA) for d in dicts], SCHEMA)


def test_the_same_finding_in_both_sources_becomes_one_row(spark):
    # 1,154 real groups look like this: a portal row and a PDF row, same batch, same month,
    # same maker, same medicine. The batch text differs only in spacing.
    out = deduplicate(rows(spark, PORTAL, PDF))

    assert out.count() == 1


def test_the_portal_row_wins(spark):
    # ADR 0004: the portal is primary from 2019, its text is cleaner and its dates parse better.
    row = deduplicate(rows(spark, PDF, PORTAL)).collect()[0]

    assert row["extraction_method"] == "api"
    assert row["source_key"] == PORTAL["source_key"]
    assert row["source_sha256"] == "aa"


def test_the_other_document_is_still_recorded(spark):
    # "This batch was published in both the state list and the portal" stays provable.
    row = deduplicate(rows(spark, PORTAL, PDF)).collect()[0]

    assert row["also_reported_in"] == [PDF["source_key"]]


def test_a_row_reported_once_has_an_empty_list_not_null(spark):
    row = deduplicate(rows(spark, PORTAL)).collect()[0]

    assert row["also_reported_in"] == []


def test_text_only_the_pdf_carries_is_kept(spark):
    # 2 real rows, one a firm's reply reading "The actual manufacturer (as per label claim) has
    # informed that the impugned batch..." - a company saying a batch is not theirs.
    reply = "The actual manufacturer has informed that the impugned batch is not theirs"
    out = deduplicate(rows(spark, PORTAL, {**PDF, "firm_reply": reply}))

    row = out.collect()[0]
    assert row["extraction_method"] == "api"  # the portal row still won
    assert row["firm_reply"] == reply  # but the PDF's text came with it


def test_provenance_is_never_blended(spark):
    # The winning row's source_key must not end up beside another document's page number.
    row = deduplicate(rows(spark, PORTAL, PDF)).collect()[0]

    assert row["source_key"] == PORTAL["source_key"]
    assert row["page"] is None  # the portal has no pages; the PDF's 3 must not leak in
    assert row["row_index"] == PORTAL["row_index"]


def test_one_batch_number_reused_across_products_is_not_one_finding(spark):
    # Real: batch TST2301 is used for five different injections by one maker. Keyed on
    # batch + month + maker alone, all ten rows collapse into one.
    products = [
        "Trenbolone Acetate Injection 100mg/ml",
        "Trenbolone Enanthate Injection 200mg/ml",
        "Nandrolone Blend Injection 350mg/ml",
        "Boldenone Undecylenate Injection 400mg/ml",
        "Stanozolol Injection 100mg/ml",
    ]
    both_sources = [
        {**side, "batch_no": "TST2301", "product_name_raw": name}
        for name in products
        for side in (PORTAL, PDF)
    ]

    out = deduplicate(rows(spark, *both_sources))

    assert out.count() == 5  # one per medicine, each pairing with its own twin


@pytest.mark.parametrize("placeholder", ["Not Applicable", "not mentioned", "NIL", "--", "-",
                                         "Not given", "NA", "N/A."])  # fmt: skip
def test_a_batch_number_that_names_no_batch_is_never_a_key(spark, placeholder):
    # 42 real rows. Grouping on "not applicable" merged three unrelated medicines.
    out = deduplicate(
        rows(
            spark,
            {**PORTAL, "batch_no": placeholder, "product_name_raw": "Medicine A"},
            {**PDF, "batch_no": placeholder, "product_name_raw": "Medicine A"},
        )
    )

    assert out.count() == 2  # kept apart: the batch number proves nothing


def test_rows_missing_a_key_part_are_never_merged(spark):
    # Spark's groupBy treats NULL as a value, so keying on a nullable column would merge rows
    # whose maker is merely unknown. This is how 10 spurious rows first appeared to duplicate
    # NSQ findings.
    out = deduplicate(
        rows(
            spark,
            {**PORTAL, "manufacturer_canonical": None},
            {**PDF, "manufacturer_canonical": None},
        )
    )

    assert out.count() == 2


def test_a_spurious_report_never_merges_into_an_nsq_finding(spark):
    # CLAUDE.md Section 6: they are different findings, and a counterfeit report must never be
    # folded into a manufacturer's own record.
    spurious = {
        **PORTAL,
        "source_dataset": "spurious",
        "is_spurious": True,
        "manufacturer_canonical": None,
        "name_on_pack": "Test Pharma Limited",
    }

    out = deduplicate(rows(spark, PORTAL, spurious))

    assert out.count() == 2


def test_two_reports_of_the_same_counterfeit_do_merge(spark):
    # A spurious row has no manufacturer by design, so the key falls back to the name printed on
    # the fake pack - still attributed to nobody.
    spurious_portal = {
        **PORTAL, "source_dataset": "spurious", "is_spurious": True,
        "manufacturer_canonical": None, "name_on_pack": "Ipca Laboratories Limited",
    }  # fmt: skip
    spurious_pdf = {
        **PDF, "source_dataset": "spurious", "is_spurious": True,
        "manufacturer_canonical": None, "name_on_pack": "Ipca Laboratories Limited",
    }  # fmt: skip

    out = deduplicate(rows(spark, spurious_portal, spurious_pdf))

    row = out.collect()[0]
    assert out.count() == 1
    assert row["manufacturer_canonical"] is None  # still attributed to nobody
    assert row["name_on_pack"] == "Ipca Laboratories Limited"


def test_the_redundant_bulk_file_is_dropped(spark):
    bulk = {**PORTAL, "source_dataset": "nsq-bulk", "alert_month": None,
            "source_key": "bronze/cdsco-pdf/nsq-bulk/2017-2023"}  # fmt: skip

    out = deduplicate(rows(spark, PORTAL, bulk))

    assert out.count() == 1
    assert out.collect()[0]["source_dataset"] == "nsq"


def test_a_different_month_is_a_different_finding(spark):
    # The same batch flagged again in a later alert month is a new report, not a duplicate.
    out = deduplicate(rows(spark, PORTAL, {**PDF, "alert_month": "2025-07"}))

    assert out.count() == 2


def test_running_it_twice_changes_nothing(spark):
    # Phase 5 re-runs this pipeline every month; the plan's acceptance test there is
    # "re-runs don't create duplicates".
    once = deduplicate(rows(spark, PORTAL, PDF))
    twice = deduplicate(once.drop("also_reported_in"))

    assert twice.count() == once.count() == 1
    assert twice.collect()[0]["also_reported_in"] == []


def test_the_winner_is_the_same_on_every_run(spark):
    # Two PDF twins of one finding and no portal row: the tie-break has to be stable, or a
    # different row wins each run and silver changes for no reason.
    other_pdf = {**PDF, "source_key": "bronze/cdsco-pdf/central-nsq/2025-06",
                 "source_sha256": "cc", "page": 1}  # fmt: skip

    winners = {
        deduplicate(rows(spark, *order)).collect()[0]["source_sha256"]
        for order in ((PDF, other_pdf), (other_pdf, PDF))
    }

    assert len(winners) == 1
