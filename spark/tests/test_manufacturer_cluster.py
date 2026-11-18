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


# --- piece 4: the reviewed decisions reaching the clustering -----------------------------


def test_a_reviewed_pair_is_merged_even_though_it_scores_below_the_threshold():
    # The whole point of piece 3: these pairs score 95-98, which is deliberately NOT enough to
    # merge automatically. Without this, a person's 260 decisions would change nothing.
    counts = {"Agron Remedies Private Limited": 5, "Argon Remedies Private Limited": 3}

    without = cluster_variants(counts)
    with_review = cluster_variants(counts, merges=[tuple(sorted(counts))])

    assert len(set(without.values())) == 2  # left apart by the scorer
    assert len(set(with_review.values())) == 1  # joined because a person said so


def test_the_reviewed_merge_still_picks_the_canonical_name_by_the_usual_rules():
    # The agreed name is the variant on the most rows, exactly as for an automatic cluster.
    counts = {"Agron Remedies Private Limited": 5, "Argon Remedies Private Limited": 3}

    mapping = cluster_variants(counts, merges=[tuple(sorted(counts))])

    assert set(mapping.values()) == {"Agron Remedies Private Limited"}


def test_a_rejected_pair_is_not_merged():
    # Only "same company" answers are passed in; "different" needs no handling, because not
    # merging is already what happens below the threshold.
    counts = {"Sarv Pharma Private Limited": 4, "Solar Pharma Private Limited": 2}

    mapping = cluster_variants(counts, merges=[])

    assert len(set(mapping.values())) == 2


def test_no_decisions_leaves_the_clustering_exactly_as_it_was():
    # CI has no decisions file; the result must be identical to the automatic clustering.
    counts = {"J.M. Laboratories": 9, "J. M. Laboratories": 2, "Unrelated Pharma Limited": 1}

    assert cluster_variants(counts) == cluster_variants(counts, merges=())


def test_a_decision_about_a_name_that_no_longer_exists_is_skipped():
    # A cleaning rule can change between the review and the next build, so a remembered name
    # may be gone. Skipping it is right; crashing or inventing a cluster is not.
    counts = {"Zee Laboratories": 3}

    mapping = cluster_variants(counts, merges=[("Zee Laboratories", "A Name Since Changed")])

    assert mapping == {"Zee Laboratories": "Zee Laboratories"}


def test_a_reviewed_merge_can_join_two_whole_clusters():
    # The reviewed pair is one edge; union-find then pulls each side's automatic cluster with
    # it. This is how "3 separate Martin & Brown clusters" become one.
    counts = {
        "Martin and Brown Bio-Sciences Private Limited": 6,
        "Martin and Brown Bio-Sciences Private Limited.": 2,  # joins the first automatically
        "Martin & Brown Bio Sciences Pvt Ltd": 3,
    }

    mapping = cluster_variants(
        counts,
        merges=[
            (
                "Martin & Brown Bio Sciences Pvt Ltd",
                "Martin and Brown Bio-Sciences Private Limited",
            )
        ],
    )

    assert len(set(mapping.values())) == 1
