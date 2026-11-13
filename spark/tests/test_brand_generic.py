"""brand_generic.py: the bracket-shape rule and the pharma-marker side rule, on real names."""

import pytest
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.brand_generic import add_brand_generic, bracket_groups, split_brand_generic


def test_generic_outside_brand_inside_the_usual_order():
    # Real example: the marker (I.P.) sits outside; the bracket holds the brand.
    result = split_brand_generic("Ampicillin Sodium Injection I.P. (AMPIVEE- 500 Injection)")

    # tidy() strips trailing punctuation left by bracket removal, including I.P.'s own final dot;
    # IP and I.P. mean the same thing to PHARMA, so no information is lost by dropping it.
    assert result == {
        "split_generic_name": "Ampicillin Sodium Injection I.P",
        "split_brand_name": "AMPIVEE- 500 Injection",
    }


def test_generic_inside_brand_outside_the_reversed_order():
    # Real example: "Senocartine" is the brand; the full composition, with its USP marker, is
    # inside the brackets. Order alone can't tell these apart - only the marker's side can.
    result = split_brand_generic("Senocartine (Levocarnitine Injection USP 1g / 5ml)")

    assert result == {
        "split_generic_name": "Levocarnitine Injection USP 1g / 5ml",
        "split_brand_name": "Senocartine",
    }


def test_marker_on_both_sides_is_not_guessed():
    # Real example: "Ringer's Lactate I.P." inside just repeats "Injection I.P." outside - the
    # same composition described twice, not a brand. Neither side is picked.
    name = "Compound Sodium Lactate Injection I.P (Ringer's Lactate I.P)"

    assert split_brand_generic(name) == {"split_generic_name": None, "split_brand_name": None}


def test_a_bare_strength_is_not_mistaken_for_a_brand():
    # Real example: the marker sits only outside, but the bracket just repeats the strength as a
    # combination, not a brand. Found by reading real output, not assumed safe in advance.
    name = "Ferrous ascorbate & folic acid tablet IP (100mg/1.5mg)"

    assert split_brand_generic(name) == {"split_generic_name": None, "split_brand_name": None}


def test_a_second_synonym_description_is_not_mistaken_for_a_brand():
    # Real example (29 occurrences, 5 spellings): "Ringer Lactate Solution for Injection" is a
    # second, synonym description of Compound Sodium Lactate, not a brand. The giveaway: a real
    # brand is never named "for" its own route of administration.
    name = "Compound Sodium Lactate Injection IP (Ringer Lactate Solution for Injection)"

    assert split_brand_generic(name) == {"split_generic_name": None, "split_brand_name": None}


def test_a_genuine_multiword_brand_ending_in_a_form_word_is_kept():
    # Real example: Indian pharma brands commonly include the dosage form in their marketed name.
    # This must still split, even though it ends in "Tablets" just like the Ringer Lactate case.
    name = "Loperamide Hydrochloride Tablets IP (DYRIA STOP TABLETS)"

    assert split_brand_generic(name) == {
        "split_generic_name": "Loperamide Hydrochloride Tablets IP",
        "split_brand_name": "DYRIA STOP TABLETS",
    }


def test_a_bare_marker_is_not_a_generic_description():
    # Real example: nothing is inside the brackets but the marker itself - no real composition.
    assert split_brand_generic("ABSORBENT COTTON WOOL (IP)") == {
        "split_generic_name": None,
        "split_brand_name": None,
    }


def test_marker_on_neither_side_is_not_guessed():
    # Real example: a vaccine name and its brand, with no pharmacopoeia marker anywhere.
    name = "Novel Corona Virus - nCoV Vaccine (ZYCOV- D)"

    assert split_brand_generic(name) == {"split_generic_name": None, "split_brand_name": None}


@pytest.mark.parametrize(
    "name",
    [
        "Pantoprazole Gastro-resistant Tablets IP",  # zero groups: no separator to split on
        "Tetanus Vaccine(adsorbed) I.P (AbhayTox)",  # two top-level groups: too ambiguous
        "Paracetamol Tablets IP 500 mg (Pararex- 500",  # unbalanced: a cut-off cell
        None,
        "",
    ],
)
def test_the_wrong_shape_is_not_split(name):
    assert split_brand_generic(name) == {"split_generic_name": None, "split_brand_name": None}


def test_nested_brackets_count_as_one_group_not_two():
    # A bracket inside a bracket (e.g. a "(Vet.)" aside) must not be read as two top-level groups.
    assert bracket_groups("A (B (C) D) E") == [(2, 10)]
    assert bracket_groups("A (B) C (D)") == [(2, 4), (8, 10)]  # genuinely two: stays unsplit


def test_a_line_break_inside_the_name_is_tidied_away():
    # Real-shaped example: PDF cells keep their line breaks.
    result = split_brand_generic("Telmisartan Tablets IP\n(Telzasig 20)")

    assert result == {
        "split_generic_name": "Telmisartan Tablets IP",
        "split_brand_name": "Telzasig 20",
    }


def test_add_brand_generic_on_a_dataframe(spark):
    schema = StructType([StructField("name", StringType())])
    rows = [("Ampicillin Sodium Injection I.P. (AMPIVEE-500)",), ("Pantoprazole Tablets IP",)]
    df = spark.createDataFrame(rows, schema)

    result = add_brand_generic(df, F.col("name")).collect()

    assert result[0]["split_generic_name"] == "Ampicillin Sodium Injection I.P"
    assert result[0]["split_brand_name"] == "AMPIVEE-500"
    assert result[1]["split_generic_name"] is None
