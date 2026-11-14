"""failure_category.py: the vocabulary, the traps real values set, and the spurious rule.

Every reason text below is a real value from the archive (or a real value with the substance name
changed), and the counts in the comments are the real row counts behind each rule.
"""

import pytest
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType, StringType, StructField, StructType

from drugwatch_spark.failure_category import (
    OTHER,
    add_failure_categories,
    categories_of,
)

SCHEMA = StructType(
    [StructField("failure_reason", StringType()), StructField("is_spurious", BooleanType())]
)


def categories(spark, reason, *, spurious=False):
    df = spark.createDataFrame([(reason, spurious)], SCHEMA)
    got = df.select(
        categories_of(F.col("failure_reason"), F.col("is_spurious")).alias("c")
    ).collect()[0]["c"]
    return set(got)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("Dissolution", {"Dissolution"}),
        ("Assay", {"Assay"}),
        ("Sterility", {"Sterility"}),
        ("Description", {"Description"}),
        ("Particulate Matter", {"Particulate"}),
        ("Disintegration", {"Disintegration"}),
        ("pH", {"pH"}),
        ("Related Substances", {"Related substances"}),
        ("Uniformity of weight", {"Uniformity"}),
        ("Loss on drying", {"Water"}),
        ("Identification", {"Identification"}),
        ("Specific gravity", {"Physical"}),
        ("Misbranded", {"Labelling"}),
    ],
)
def test_the_plain_single_test_reasons(spark, reason, expected):
    assert categories(spark, reason) == expected


def test_a_row_that_failed_two_tests_is_counted_under_both(spark):
    # 1,183 real rows (14%) name more than one test; this is why it is a list.
    assert categories(spark, "Dissolution and Assay") == {"Dissolution", "Assay"}


def test_a_row_that_failed_five_tests_keeps_all_five(spark):
    reason = "ph, clarity of solution, particulate matter, related substances and assay of X"
    assert categories(spark, reason) == {
        "pH", "Particulate", "Related substances", "Assay",
    }  # fmt: skip


def test_a_reason_split_across_a_line_break_matches_the_same_as_one_line(spark):
    # clean_text.py keeps line breaks on purpose, so "dissolution (for calcium)" (48 rows) and
    # the same text broken by the PDF (24 rows) are two raw values that must land together.
    assert categories(spark, "Dissolution (for\nCalcium)") == categories(
        spark, "Dissolution (for Calcium)"
    )


def test_a_whole_sentence_is_read_the_same_as_the_bare_test_name(spark):
    reason = "The sample does not conform to I.P. w.r.to the tests for Dissolution"
    assert categories(spark, reason) == {"Dissolution"}


def test_content_counts_as_assay(spark):
    # Harith's decision: an assay IS a content determination, and CDSCO writes both.
    assert categories(spark, "Content") == {"Assay"}
    assert categories(spark, "Assay/Content of Cholecalciferol (Vitamin D3)") == {"Assay"}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("Water content", {"Water"}),  # not Assay, though it says "content"
        ("Moisture content", {"Water"}),
        ("Uniformity of content", {"Uniformity"}),  # the uniformity test, not the assay
    ],
)
def test_content_in_another_tests_name_is_not_assay(spark, reason, expected):
    assert categories(spark, reason) == expected


def test_label_claim_is_an_assay_failure_not_a_labelling_offence(spark):
    # 105 real rows. Counting these as Labelling reported 390 labelling offences where the
    # archive holds about a quarter of that - and mislabelling is an accusation, so it has to be
    # the offence CDSCO actually recorded (CLAUDE.md Section 6).
    reason = "Sample does not conform to label claim with respect to the content of Oxetacaine"

    assert categories(spark, reason) == {"Assay"}


def test_a_shortfall_against_the_labelled_amount_is_an_assay_failure(spark):
    # The same trap as "label claim", in different words: "labelled amount" is the declared
    # strength, so this row reports a strength shortfall, not a wrong label.
    reason = (
        "The content of Vitamin D3 in the sample is less (i.e. 34.85% of the labelled amount) "
        "than the IP limit"
    )

    assert categories(spark, reason) == {"Assay"}


@pytest.mark.parametrize(
    "reason",
    [
        "Sample does not conform to label claim with respect to the content of Oxetacaine",
        "The content of Vitamin D3 is less (i.e. 34.85% of the labelled amount) than the IP limit",
        "Sample does not conform to label with respect to the content of available iodine",
        "Content of mecobalamin found to be 2.38 mg per ml against labelled claim of 2500 mg",
    ],
)
def test_no_phrasing_of_the_declared_strength_is_read_as_a_labelling_offence(spark, reason):
    # All four are real. "label" in this archive usually means the declared strength, so the
    # Labelling pattern allow-lists real labelling phrasings instead of matching the bare word.
    assert categories(spark, reason) == {"Assay"}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("1) manufacturing date is not mentioned on the label.", {"Labelling"}),
        # fmt: off
        ("nature of tablets such as uncoated or film coated not declared on the label",
         {"Labelling"}),
        # fmt: on
        ("The product is official in USP which is not printed on the strips", {"Labelling"}),
        ("incorrect labelling", {"Labelling"}),
    ],
)  # fmt: skip
def test_a_real_labelling_offence_is_still_caught(spark, reason, expected):
    assert categories(spark, reason) == expected


def test_water_for_injection_is_a_product_name_not_the_water_test(spark):
    # 8 real rows: "sterility of water for injection" is a sterility failure only.
    assert categories(spark, "Sterility of Water for Injection") == {"Sterility"}


@pytest.mark.parametrize(
    "reason",
    [
        "diabetes",  # must not match "bet" (the Bacterial Endotoxin Test)
        "Betamethasone Valerate",
        "morphine",  # must not match "ph"
        "graph",
    ],
)
def test_a_short_token_does_not_match_inside_a_longer_word(spark, reason):
    # The reason every pattern is bounded: "bet" and "ph" are 2-3 letters.
    assert categories(spark, reason) == {OTHER}


def test_bet_on_its_own_is_the_endotoxin_test(spark):
    assert categories(spark, "BET") == {"Sterility"}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("misbrandad", {"Labelling"}),  # 13 real rows
        ("sterillity", {"Sterility"}),  # 6
        ("Matter insoluble in alochol", {"Physical"}),  # 6
        ("related susbtances", {"Related substances"}),  # 3
        ("suspension does not dispose uniformaly on shaking", {"Uniformity"}),  # 3
        ("mottled appeareance", {"Description"}),  # 2
    ],
)
def test_cdscos_own_misspellings_still_find_their_category(spark, reason, expected):
    # A typo in CDSCO's text is not a reason to lose the row's category.
    assert categories(spark, reason) == expected


def test_a_reason_naming_no_test_becomes_other(spark):
    for reason in ("NSQ", "Not applicable", "Does not conform to I.P.", "Not of standard quality"):
        assert categories(spark, reason) == {OTHER}, reason


def test_no_reason_at_all_gives_an_empty_list_not_other(spark):
    # Nothing was reported, which is different from "a reason we could not place".
    assert categories(spark, None) == set()
    assert categories(spark, "   ") == set()


def test_spurious_comes_from_the_flag_not_from_the_word(spark):
    # One real NSQ row ends "...the tests for identification and assay spurious". The word
    # appears in 264 rows' text; only 77 rows are spurious reports (CLAUDE.md Section 6).
    reason = (
        "The sample does not conform to I.P. w.r.to the tests for identification and assay spurious"
    )

    assert categories(spark, reason, spurious=False) == {"Identification", "Assay"}


def test_a_spurious_row_is_marked_spurious_and_keeps_its_lab_tests(spark):
    # The tests were really run - on the seized counterfeit sample. Nothing is attributed to a
    # manufacturer either way: build_silver already nulls every manufacturer column there.
    got = categories(spark, "Identification and Assay", spurious=True)

    assert got == {"Spurious", "Identification", "Assay"}


def test_a_spurious_row_with_no_reason_is_still_spurious(spark):
    assert categories(spark, None, spurious=True) == {"Spurious"}


def test_the_column_is_added_without_dropping_anything(spark):
    df = spark.createDataFrame([("Dissolution", False), ("Assay", True)], SCHEMA)

    out = add_failure_categories(df)

    assert out.count() == 2
    assert set(df.columns) <= set(out.columns)
    assert "failure_categories" in out.columns
