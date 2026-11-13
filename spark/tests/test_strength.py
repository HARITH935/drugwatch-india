"""strength.py: every rule, on real product names from the archive."""

import pytest
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.strength import add_strengths, strengths_in, tidy_number


@pytest.mark.parametrize(
    ("name", "form", "expected"),
    [
        # one plain strength; the brand's bare "300" has no unit, so it doesn't count
        ("Quinine Sulphate Tablets IP 300 mg (REZ-Q* 300)", "Tablet", ["300 mg"]),
        # concentrations: the bottom is a volume, or "per gram"
        ("Amoxycillin Oral Suspension I.P. 125mg/5ml Dry Syrup", "Suspension", ["125 mg/5 ml"]),
        ("Frusemide Injection IP 10mg / ml (Senfuro)", "Injection", ["10 mg/ml"]),
        ("Methylcobalamin Injection 1500 mcg / 2 ml", "Injection", ["1500 mcg/2 ml"]),
        ("Heparin Injection IP 5000 IU/ml (Flagorin)", "Injection", ["5000 IU/ml"]),
        ("Cholecalciferol (Vitamin D3) 60000 IU/gm Granule Sachet", "Granules", ["60000 IU/g"]),
        # a slash between two masses joins two strengths of a combination
        (
            "Telmisartan and Hydrochlorothiazide Tablets I.P (40mg/12.5mg)",
            "Tablet",
            ["40 mg", "12.5 mg"],
        ),
        # percentages, with or without a space before w/v
        ("Mannitol Injection I.P. (20% w/v)", "Injection", ["20% w/v"]),
        ("Ciprofloxacin Injection IP (0.2%w/v)", "Injection", ["0.2% w/v"]),
        ("Bupivacaine Hydrochloride Injection IP (Bupicain-0.5%)", "Injection", ["0.5%"]),
        # PDF cells keep their line breaks
        ("Nandrolone\nDecanoate Injection\nIP 50 mg/ml", "Injection", ["50 mg/ml"]),
    ],
)
def test_real_strengths_are_found_and_written_one_way(name, form, expected):
    assert strengths_in(name, form) == expected


def test_a_bare_ml_is_a_bottle_size_not_a_strength():
    assert strengths_in("Bimatoprost Eye Drops 3 ml", "Drops") == []


def test_a_bare_gram_counts_only_for_an_injection():
    assert strengths_in("Ceftriaxone for Injection I.P. 1 gm", "Injection") == ["1 g"]
    # Real: the 30 g is the tube; the 5% w/v is the strength.
    assert strengths_in("Lignocaine Hydrochloride Gel IP 5 % w/v (30 g)", "Gel") == ["5% w/v"]
    # Real: a needle gauge, not a strength.
    assert strengths_in("Ophthalmic Solution with Angular Cannula 23G", "Solution") == []


def test_a_number_glued_to_a_letter_is_skipped_not_misread():
    # Real: this is Vitamin D3 + 250 IU. Reading "3250 IU" would be wrong, so it's skipped.
    assert strengths_in("Calcium 500 mg withVitaminD3250 IU Tablets IP", "Tablet") == ["500 mg"]


def test_repeats_are_kept_because_combinations_can_share_a_value():
    # Real: two ingredients, both 250 mg. Removing the repeat would lose Cloxacillin's strength.
    name = "Amoxycillin 250 mg and Cloxacillin 250 mg Capsules"

    assert strengths_in(name, "Capsule") == ["250 mg", "250 mg"]


def test_thousands_commas_and_extra_zeros_are_tidied():
    assert strengths_in("Vitamin D3 Chewable Tablets 60,000 IU", "Tablet") == ["60000 IU"]
    assert strengths_in("Ceftriaxone Injection I.P. 1.0 g", "Injection") == ["1 g"]
    assert strengths_in("Bupivacaine Inj. USP 0.50%", "Injection") == ["0.5%"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,00,000", "100000"),
        ("1.0", "1"),
        ("10.0", "10"),
        ("0.50", "0.5"),
        ("05", "5"),
        ("100", "100"),
        ("12.5", "12.5"),
        ("0", "0"),
    ],
)
def test_tidy_number(text, expected):
    assert tidy_number(text) == expected


@pytest.mark.parametrize("name", [None, "", "Disposable Syringes (SUI)"])
def test_no_strength_gives_an_empty_list(name):
    assert strengths_in(name, None) == []


def test_add_strengths_on_a_dataframe(spark):
    schema = StructType([StructField("name", StringType()), StructField("form", StringType())])
    rows = [("Ceftriaxone Injection IP 1g", "Injection"), ("Gentamicin Inj. IP", "Injection")]
    df = spark.createDataFrame(rows, schema)

    result = add_strengths(df, F.col("name"), F.col("form")).collect()

    assert [r["strengths"] for r in result] == [["1 g"], []]
