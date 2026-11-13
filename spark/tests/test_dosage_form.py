"""dosage_form.py: the form vocabulary and its two rules, on real product names from the archive."""

import pytest
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.dosage_form import add_dosage_form

SCHEMA = StructType([StructField("name", StringType())])


def form_of(spark, name):
    df = spark.createDataFrame([(name,)], SCHEMA)
    row = add_dosage_form(df, F.col("name")).collect()[0]
    return row["dosage_form"], row["dosage_forms_found"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Telmisartan Tablets IP (Telzasig 20)", "Tablet"),
        ("Telma 40 (Telmisartan Tab I.P. 40mg)", "Tablet"),  # abbreviation
        ("Gentamicin Inj. IP", "Injection"),  # abbreviation with a dot
        ("Oseltamivir Cap IP 75 mg", "Capsule"),
        ("Amoxycillin Oral Suspension I.P. 125mg/5ml", "Suspension"),
        ("Oxfendazole & Ivermectin Bolus (Vet.)", "Bolus"),
        ("Telmisartan\nTablets IP", "Tablet"),  # PDF cells keep their line breaks
        ("PARACETAMOL TABLETS IP 500 MG", "Tablet"),  # case doesn't matter
    ],
)
def test_one_form_word_gives_that_form(spark, name, expected):
    assert form_of(spark, name)[0] == expected


def test_injection_wins_when_the_name_also_says_how_it_is_made(spark):
    # Real name: a Solution FOR Injection is an injection. All 62 such real names are like this.
    name = "Compound Sodium Lactate Injection IP (Ringer Lactate Solution for Injection)"

    assert form_of(spark, name) == ("Injection", ["Injection", "Solution"])


def test_any_other_mix_stays_null_but_shows_what_was_seen(spark):
    # Real name: eye drops that are an ophthalmic solution. No rule checked for this mix yet.
    form, found = form_of(spark, "Ofloxacin Ophthanmic Solution IP (Ocuex Eye Drops)")

    assert form is None
    assert found == ["Solution", "Drops"]  # so the null can always be explained


def test_an_abbreviation_glued_to_a_brand_is_not_a_form(spark):
    # Real name: "NS-CAP" is the brand. Without the hyphen guard this also matched Capsule.
    assert form_of(spark, "NS-CAP Sodium Chloride Injection IP 0.9% w/v") == (
        "Injection",
        ["Injection"],
    )


def test_gelatin_is_not_gel(spark):
    assert form_of(spark, "Vitamin E Acetate Soft Gelatin Capsules")[0] == "Capsule"


@pytest.mark.parametrize(
    "name",
    [
        "Bio Typh (Vi Polysaccaride Typhoid Vaccine) I.P.",  # the name doesn't say the form
        "Disposable Syringes (5ml) (SUI)",  # a device: no dosage form at all
        "Vitamin E Acetate Soft Gelatin Caspules",  # CDSCO typo: not guessed
        None,
        "",
    ],
)
def test_no_form_word_stays_null(spark, name):
    assert form_of(spark, name) == (None, [])
