"""build_silver.py: the pieces composing, the shared schema, and the spurious rule."""

import datetime

import pytest
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

from drugwatch_spark.build_silver import (
    SILVER_COLUMNS,
    build_silver,
    clean_pdf,
    clean_portal,
    clean_shared,
    product_name_of,
    to_silver_columns,
)

PDF_SCHEMA = StructType(
    [
        StructField(name, StringType())
        for name in (
            "source_dataset", "source_key", "source_sha256", "source_url", "alert_month",
            "extraction_method", "batch_no", "mfg_date", "expiry_date", "product_name",
            "manufacturer", "failure_reason", "reported_by", "remarks", "firm_reply",
        )
    ]
    + [StructField("page", IntegerType()), StructField("row_index", IntegerType())]
)  # fmt: skip
PORTAL_SCHEMA = StructType(
    [
        StructField(name, StringType())
        for name in (
            "source_dataset", "source_key", "source_sha256", "source_url", "alert_month",
            "extraction_method", "batch_no", "mfg_date", "expiry_date", "product_name",
            "generic_name", "brand_name", "manufacturer", "failure_reason", "reported_by",
            "remarks", "firm_reply",
        )
    ]
    + [StructField("row_index", IntegerType())]
)  # fmt: skip


def pdf_row(spark, **over):
    row = {
        "source_dataset": "central-nsq", "source_key": "raw/a.pdf", "source_sha256": "abc",
        "source_url": "https://cdsco/x.pdf", "alert_month": "2024-06",
        "extraction_method": "rule", "batch_no": "TB-1201", "mfg_date": "10/2023",
        "expiry_date": "09/2025", "product_name": "Telmisartan Tablets IP 40 mg (TELSAT 40)",
        "manufacturer": "M/s. Test Pharma Ltd., Plot 7, Baddi", "failure_reason": "Assay",
        "reported_by": "CDL Kolkata", "remarks": "", "firm_reply": "", "page": 2, "row_index": 5,
    }  # fmt: skip
    row.update(over)
    return spark.createDataFrame([tuple(row[f.name] for f in PDF_SCHEMA)], PDF_SCHEMA)


def portal_row(spark, **over):
    row = {
        "source_dataset": "nsq", "source_key": "raw/p.json", "source_sha256": "def",
        "source_url": "https://cdsco/p", "alert_month": "2024-06", "extraction_method": "api",
        "batch_no": "PT-9", "mfg_date": "Aug-2017", "expiry_date": "Jul-2022",
        "product_name": None, "generic_name": "Paracetamol Tablets IP 500 mg (Pacimol)",
        "brand_name": "NA", "manufacturer": "M/s. Portal Pharma Ltd., Baddi",
        "failure_reason": "Dissolution", "reported_by": "CDL Mumbai", "remarks": "",
        "firm_reply": "", "row_index": 1,
    }  # fmt: skip
    row.update(over)
    return spark.createDataFrame([tuple(row[f.name] for f in PORTAL_SCHEMA)], PORTAL_SCHEMA)


def test_the_medicine_name_is_found_wherever_the_source_keeps_it(spark):
    # Portal NSQ rows keep it in generic_name, PDF rows in product_name.
    portal = portal_row(spark)
    pdf = pdf_row(spark)

    assert portal.select(product_name_of(portal)).collect()[0][0].startswith("Paracetamol")
    assert pdf.select(product_name_of(pdf)).collect()[0][0].startswith("Telmisartan")


def test_a_portal_spurious_row_uses_product_name_not_generic_name(spark):
    df = portal_row(spark, source_dataset="spurious", generic_name=None,
                    product_name="Fake Tablets IP")  # fmt: skip

    assert df.select(product_name_of(df)).collect()[0][0] == "Fake Tablets IP"


def test_every_shared_step_runs_and_fills_its_own_column(spark):
    row = clean_shared(clean_pdf(pdf_row(spark))).collect()[0]

    assert row["dosage_form"] == "Tablet"
    assert row["strengths"] == ["40 mg"]
    assert row["split_generic_name"] == "Telmisartan Tablets IP 40 mg"
    assert row["split_brand_name"] == "TELSAT 40"
    assert row["manufacturer_name"] == "Test Pharma Limited"


def test_strengths_are_worked_out_after_the_dosage_form_not_before(spark):
    # A bare gram is a strength only on an injection (elsewhere it is a tube or pack size), so
    # add_strengths needs the dosage_form column to already hold "Injection". Run in the wrong
    # order, this row's strength silently comes back empty.
    df = pdf_row(spark, product_name="Ceftriaxone for Injection I.P. 1 gm")

    row = clean_shared(clean_pdf(df)).collect()[0]

    assert row["dosage_form"] == "Injection"
    assert row["strengths"] == ["1 g"]


def test_both_sources_land_on_the_same_columns(spark):
    pdf = to_silver_columns(clean_shared(clean_pdf(pdf_row(spark))))
    portal = to_silver_columns(clean_shared(clean_portal(portal_row(spark))))

    assert pdf.columns == portal.columns


def test_dates_from_both_sources_end_up_parsed(spark):
    silver = build_silver(pdf_row(spark), portal_row(spark))
    by_method = {r["extraction_method"]: r for r in silver.collect()}

    assert by_method["rule"]["mfg_date"] == datetime.date(2023, 10, 1)  # "10/2023"
    assert by_method["api"]["mfg_date"] == datetime.date(2017, 8, 1)  # "Aug-2017"
    assert by_method["rule"]["mfg_date_raw"] == "10/2023"  # what the document printed


COMBINED_CELL = (  # the real shape of the 9 portal rows fix_portal_batch repairs (2019-01)
    "B. No.: TP-3286,\nMfg dt: 03/2018, Exp dt: 02/2020, Mfd by: M/s. Ticoma\nPharmacia, Baddi"
)


def test_the_raw_columns_show_what_the_portal_published_not_the_correction(spark):
    # On those 9 rows the portal's own batch_no is stale and the true values sit inside the
    # manufacturer cell. fix_portal_batch overwrites batch_no/mfg_date/expiry_date/manufacturer
    # in place, so the snapshot has to be taken BEFORE it runs - otherwise silver's `_raw`
    # columns show the corrected value and the portal's error disappears from the record.
    df = portal_row(spark, batch_no="STALE-9", mfg_date="Jan-2015", expiry_date="Dec-2016",
                    manufacturer=COMBINED_CELL)  # fmt: skip

    row = build_silver(pdf_row(spark), df).where("extraction_method = 'api'").collect()[0]

    assert row["batch_no"] == "TP-3286"  # corrected, from inside the cell
    assert row["batch_no_raw"] == "STALE-9"  # what the portal actually published
    assert row["mfg_date_raw"] == "Jan-2015"
    assert row["expiry_date_raw"] == "Dec-2016"
    assert row["manufacturer_raw"] == COMBINED_CELL  # the whole cell, as published


def test_dates_rescued_from_a_combined_cell_are_still_parsed(spark):
    # The dates inside the combined cell are written CDSCO's PDF way ("03/2018"), not the
    # portal's "Mon-YYYY". Verified on the real archive: parsing portal rows with the portal
    # format alone loses both dates on all 9 of these rows.
    df = portal_row(spark, mfg_date="Jan-2015", expiry_date="Dec-2016",
                    manufacturer=COMBINED_CELL)  # fmt: skip

    row = build_silver(pdf_row(spark), df).where("extraction_method = 'api'").collect()[0]

    assert row["mfg_date"] == datetime.date(2018, 3, 1)  # 03/2018, out of the cell
    assert row["expiry_date"] == datetime.date(2020, 2, 1)  # 02/2020
    assert row["dates_valid"] is True


def test_an_ordinary_portal_date_is_still_read_the_portal_way(spark):
    # The fallback must not change the 6,892 rows the portal format already parses. "Aug-2017"
    # is one of the PDF formats too (MMM-yyyy), so this also proves the two agree where they
    # overlap rather than one quietly overriding the other.
    silver = build_silver(pdf_row(spark), portal_row(spark))
    row = silver.where("extraction_method = 'api'").collect()[0]

    assert row["mfg_date"] == datetime.date(2017, 8, 1)


def test_a_real_company_named_on_a_fake_pack_is_never_attributed(spark):
    # Real: 7 portal and 10 PDF spurious rows name legitimate companies whose identity was
    # counterfeited (Ipca, Sun Pharma, Glenmark...). Counting those against them would accuse a
    # victim of counterfeiting - CLAUDE.md Section 6.
    counterfeited = "Ipca Laboratories Ltd. 393/394, Melli Jorethang Road, Sikkim 737 121"
    df = portal_row(spark, source_dataset="spurious", manufacturer=counterfeited,
                    generic_name=None, product_name="Fake Tablets IP")  # fmt: skip

    row = build_silver(pdf_row(spark), df).where("is_spurious").collect()[0]

    assert row["manufacturer_canonical"] is None  # never attributed
    assert row["manufacturer_name"] is None
    # Kept as the pack's printed name. The plot number rides along because the name/address cut
    # is the first comma and this address starts before one - manufacturer_name.py's documented
    # behaviour, and the safe direction: keeping extra text splits clusters, dropping it merges.
    assert row["name_on_pack"] == "Ipca Laboratories Limited 393/394"
    assert row["manufacturer_raw"] == counterfeited  # provenance: what the alert said


def test_an_ordinary_row_is_still_attributed(spark):
    row = build_silver(pdf_row(spark), portal_row(spark)).where("not is_spurious").collect()[0]

    assert row["manufacturer_canonical"] is not None
    assert row["name_on_pack"] is None


def test_one_company_spelled_two_ways_across_the_sources_becomes_one(spark):
    # The whole point of clustering across both sources rather than per-source.
    pdf = pdf_row(spark, manufacturer="M/s. Jackson Laboratories Pvt. Ltd., Plot 7, Baddi")
    portal = portal_row(spark, manufacturer="Jackson Laboratories Private.Limited, Baddi")

    canonical = {r["manufacturer_canonical"] for r in build_silver(pdf, portal).collect()}

    assert len(canonical) == 1


def test_silver_keeps_every_column_it_promises(spark):
    silver = build_silver(pdf_row(spark), portal_row(spark))

    assert silver.columns == SILVER_COLUMNS


def test_every_row_can_be_traced_back_to_its_document(spark):
    for row in build_silver(pdf_row(spark), portal_row(spark)).collect():
        assert row["source_key"] and row["source_sha256"] and row["source_url"]
        assert row["alert_month"] and row["extraction_method"]


@pytest.mark.parametrize("dataset", ["spurious", "central-nsq"])
def test_row_counts_are_never_changed_by_the_pipeline(spark, dataset):
    # add_canonical_manufacturer joins a lookup table: a duplicate key there would silently
    # multiply rows, which would inflate every count built on silver.
    pdf = pdf_row(spark, source_dataset=dataset)

    assert build_silver(pdf, portal_row(spark)).count() == 2


def test_a_reviewed_merge_reaches_silver(spark, monkeypatch):
    # The wiring step 5 piece 3 was missing: the review tool wrote decisions.jsonl, but nothing
    # read it, so a person's answers changed nothing. These two names score 95-98 - deliberately
    # below the automatic threshold - so they only merge because someone said they are one firm.
    pdf = pdf_row(spark, manufacturer="M/s. Agron Remedies Pvt. Ltd., Plot 7, Baddi")
    portal = portal_row(spark, manufacturer="M/s. Argon Remedies Pvt. Ltd., Baddi")

    unreviewed = build_silver(pdf, portal).select("manufacturer_canonical").distinct().count()

    monkeypatch.setattr(
        "drugwatch_spark.build_silver.merges_from_decisions",
        lambda: [("Agron Remedies Private Limited", "Argon Remedies Private Limited")],
    )
    reviewed = build_silver(pdf, portal).select("manufacturer_canonical").distinct().count()

    assert unreviewed == 2  # the scorer leaves them apart, on purpose
    assert reviewed == 1  # the decision is what joins them


def test_silver_is_unchanged_when_nobody_has_reviewed_anything(spark, monkeypatch):
    # CI and a fresh clone have no decisions file; the pipeline must behave exactly as before.
    monkeypatch.setattr("drugwatch_spark.build_silver.merges_from_decisions", list)

    silver = build_silver(pdf_row(spark), portal_row(spark))

    assert silver.count() == 2
    assert silver.where("manufacturer_canonical is not null").count() == 2
