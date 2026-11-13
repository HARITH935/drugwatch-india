"""manufacturer_cluster.py: the 98 threshold, the clustering, and the canonical pick."""

from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.manufacturer_cluster import (
    add_canonical_manufacturer,
    canonical_for,
    cluster_variants,
    review_candidates,
)


def test_real_spelling_variants_are_merged():
    # Real cluster: singular/plural, a stray second space, punctuation, case.
    counts = {
        "Rivpra Formulations Private Limited": 20,
        "Rivpra Formulation Private Limited": 5,
        "Rivpra Formulations Private.Limited": 3,
        "Rivpra Formulations Private LIMITED.": 1,
    }

    mapping = cluster_variants(counts)

    assert set(mapping.values()) == {"Rivpra Formulations Private Limited"}


def test_real_ocr_noise_is_merged():
    # Real cluster: "?" and a smart quote stand in for the apostrophe.
    counts = {"Healer's Lab Unit II": 5, "Healer?s Lab Unit II": 2, "Healer’s Lab Unit II": 1}

    assert len(set(cluster_variants(counts).values())) == 1


def test_different_companies_sharing_a_generic_tail_are_not_merged():
    # All real, all score 92-96 on the generic tail alone - exactly the merges to avoid.
    counts = {
        "RPL (INDIA) Pharmaceuticals Private Limited": 3,
        "ZRS Pharmaceuticals India Private Limited": 3,
        "Sarv Pharmaceuticals": 2,
        "Solar Pharmaceuticals": 2,
        "PRS Pharmaceuticals Private Limited": 1,
        "Pulse Pharmaceuticals Private Limited": 1,
    }

    mapping = cluster_variants(counts)

    assert len(set(mapping.values())) == len(counts)  # every one kept separate
    assert all(variant == canonical for variant, canonical in mapping.items())


def test_a_name_with_no_variants_maps_to_itself():
    assert cluster_variants({"Lone Pharma Private Limited": 1}) == {
        "Lone Pharma Private Limited": "Lone Pharma Private Limited"
    }


def test_no_names_at_all():
    assert cluster_variants({}) == {}


def test_canonical_is_the_variant_on_the_most_rows():
    counts = {
        "Jackson Laboratories Private Limited": 79,
        "Jackson Laboratories Private.Limited": 17,
    }

    assert canonical_for(list(counts), counts) == "Jackson Laboratories Private Limited"


def test_canonical_prefers_readable_casing_when_counts_tie():
    # Real tie (6 of 436 clusters): alphabetical alone would pick the shouty spelling.
    counts = {"UPKAR PHARMACEUTICALS": 2, "Upkar Pharmaceuticals": 2}

    assert canonical_for(list(counts), counts) == "Upkar Pharmaceuticals"


def test_canonical_falls_back_to_alphabetical_so_it_is_never_arbitrary():
    counts = {"Beta Pharma Private Limited": 2, "Alpha Labs Private Limited": 2}

    assert canonical_for(list(counts), counts) == "Alpha Labs Private Limited"


def test_review_candidates_are_the_near_misses_not_the_merges():
    counts = {
        "Rivpra Formulations Private Limited": 5,  # 98+ pair -> merged, not reviewed
        "Rivpra Formulation Private Limited": 5,
        "UPKAR PHARMACEUTIALS": 2,  # ~97 pair -> offered for review
        "Upkar Pharmaceuticals": 2,
        "Sarv Pharmaceuticals": 1,  # ~92 pair -> neither merged nor reviewed
        "Solar Pharmaceuticals": 1,
    }

    pairs = {(left, right) for left, right, _ in review_candidates(counts)}

    assert ("UPKAR PHARMACEUTIALS", "Upkar Pharmaceuticals") in pairs
    assert (
        "Rivpra Formulation Private Limited",
        "Rivpra Formulations Private Limited",
    ) not in pairs
    assert ("Sarv Pharmaceuticals", "Solar Pharmaceuticals") not in pairs


def test_add_canonical_manufacturer_on_a_dataframe(spark):
    schema = StructType([StructField("manufacturer_name", StringType())])
    rows = [
        ("Apple Formulations Private Limited",),
        ("Apple Formulations Private Limited",),
        ("Apple Formulation Private Limited",),  # variant, merges into the one above
        ("Lone Pharma Private Limited",),  # no variants, keeps its own name
        (None,),  # a placeholder from piece 1 stays null
    ]
    df = spark.createDataFrame(rows, schema)

    result = add_canonical_manufacturer(df, F.col("manufacturer_name")).collect()
    canonical = {row["manufacturer_name"]: row["manufacturer_canonical"] for row in result}

    assert canonical["Apple Formulation Private Limited"] == "Apple Formulations Private Limited"
    assert canonical["Lone Pharma Private Limited"] == "Lone Pharma Private Limited"
    assert canonical[None] is None
