"""manufacturer_name.py: the address boundary rule and its two sanity checks, on real names."""

from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.manufacturer_name import add_clean_manufacturer_name, clean_manufacturer_name


def test_a_clean_comma_separated_value_splits_at_the_comma():
    # Real example: name ends in a legal suffix, then a comma, then the address.
    result = clean_manufacturer_name(
        "M/s. SRS Meditech Ltd., I-14, UPSIDC, Site-V, Kasna, Greater Noida-201306"
    )

    assert result["manufacturer_name"] == "SRS Meditech Limited"
    assert result["manufacturer_address"] == "I-14, UPSIDC, Site-V, Kasna, Greater Noida-201306"


def test_no_comma_but_a_legal_suffix_still_finds_the_boundary():
    # Real example: no comma anywhere, but "Pvt Ltd" marks where the name ends.
    result = clean_manufacturer_name(
        "M/s. Himalaya Meditek Pvt Ltd Plot No. 35 & 36 Pharmacity Selaqui Ind. Area Dehradun"
    )

    assert result["manufacturer_name"] == "Himalaya Meditek Private Limited"
    assert (
        result["manufacturer_address"] == "Plot No. 35 & 36 Pharmacity Selaqui Ind. Area Dehradun"
    )


def test_an_ownership_aside_stays_part_of_the_name_not_the_address():
    # Real example (2 real companies, 49 occurrences): the parenthetical describes who the
    # company belongs to - it is identifying information, not a postal address.
    name = (
        "M/s. Paschim Banga Pharmaceuticals, (A Unit of Farista Vanijya Pvt. Ltd), "
        "NH-31, TIN MILE HAT, Sonapur HAT"
    )

    result = clean_manufacturer_name(name)

    assert (
        result["manufacturer_name"]
        == "Paschim Banga Pharmaceuticals, (A Unit of Farista Vanijya Private Limited)"
    )  # noqa: E501
    assert result["manufacturer_address"] == "NH-31, TIN MILE HAT, Sonapur HAT"


def test_neither_a_comma_nor_a_suffix_is_kept_whole_not_guessed():
    # Real example: the name runs straight into the address with no separator at all.
    text = "Affy Parenterals Vill. Gullawala P.O Baddi Distt. Solan 173205 (HP)"

    result = clean_manufacturer_name(text)

    assert result["manufacturer_name"] == text
    assert result["manufacturer_address"] is None


def test_the_m_s_prefix_is_stripped_in_its_common_spellings():
    for text in ("M/s. Test Pharma, Baddi", "M/s.Test Pharma, Baddi", "M / s Test Pharma, Baddi"):
        assert clean_manufacturer_name(text)["manufacturer_name"] == "Test Pharma"


def test_pvt_and_ltd_are_spelled_out():
    result = clean_manufacturer_name("Verax Life Sciences Pvt. Ltd., K.No. 435, Baddi")

    assert result["manufacturer_name"] == "Verax Life Sciences Private Limited"


def test_a_placeholder_is_not_a_real_manufacturer():
    for text in ("Spurious", "Not mentioned", "Not applicable", "Under Investigation", "NIL"):
        assert clean_manufacturer_name(text) == {
            "manufacturer_name": None,
            "manufacturer_address": None,
        }


def test_none_and_empty_are_not_a_real_manufacturer():
    assert clean_manufacturer_name(None) == {
        "manufacturer_name": None,
        "manufacturer_address": None,
    }
    assert clean_manufacturer_name("") == {"manufacturer_name": None, "manufacturer_address": None}


def test_a_line_break_inside_the_value_is_tidied_away():
    # Real-shaped example: PDF cells keep their line breaks.
    result = clean_manufacturer_name("M/s. Navkar Lifesciences,\nPlot No. 76, Baddi")

    assert result["manufacturer_name"] == "Navkar Lifesciences"
    assert result["manufacturer_address"] == "Plot No. 76, Baddi"


def test_add_clean_manufacturer_name_on_a_dataframe(spark):
    schema = StructType([StructField("manufacturer", StringType())])
    rows = [("M/s. Test Pharma Ltd., Plot 7, Baddi",), ("Spurious",)]
    df = spark.createDataFrame(rows, schema)

    result = add_clean_manufacturer_name(df, F.col("manufacturer")).collect()

    assert result[0]["manufacturer_name"] == "Test Pharma Limited"
    assert result[0]["manufacturer_address"] == "Plot 7, Baddi"
    assert result[1]["manufacturer_name"] is None
