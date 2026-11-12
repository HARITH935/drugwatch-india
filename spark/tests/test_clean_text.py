"""clean_text.py: whitespace rules, checked against the real quirks found in portal bronze data."""

from pyspark.sql.types import StringType, StructField, StructType

from drugwatch_spark.clean_text import normalize_whitespace


def cleaned(spark, value, column="manufacturer"):
    # An explicit schema: Spark can't infer a column's type from one row whose only value is None.
    schema = StructType([StructField(column, StringType())])
    df = spark.createDataFrame([(value,)], schema)
    return normalize_whitespace(df, [column]).collect()[0][column]


def test_a_run_of_spaces_mid_line_becomes_one_space(spark):
    # Real portal example: "Mfg dt:  05/2018, Exp dt:  04/2020,"
    assert (
        cleaned(spark, "Mfg dt:  05/2018, Exp dt:  04/2020,") == "Mfg dt: 05/2018, Exp dt: 04/2020,"
    )


def test_leading_and_trailing_space_on_the_whole_value_is_removed(spark):
    assert cleaned(spark, "  M/s. Test Pharma  ") == "M/s. Test Pharma"


def test_each_lines_own_leading_and_trailing_space_is_removed(spark):
    value = "line one\n   line two with leading space\nline three  "
    assert cleaned(spark, value) == "line one\nline two with leading space\nline three"


def test_a_meaningful_blank_line_between_two_facts_is_kept(spark):
    # Real portal example: one manufacturer field states the maker, then (blank line) the marketer.
    value = "M/s.Accuwell Medics Pvt Ltd\n\nMrk. By : Heal Sure Lifesciences Pvt Ltd"

    assert cleaned(spark, value) == value  # nothing here needed fixing; the blank line stays


def test_leading_and_trailing_blank_lines_are_removed(spark):
    assert cleaned(spark, "\n\ntext\n") == "text"


def test_a_non_breaking_space_becomes_a_regular_space(spark):
    assert cleaned(spark, "with nbsp here") == "with nbsp here"


def test_a_tab_is_treated_the_same_as_a_space(spark):
    assert cleaned(spark, "col1\t\tcol2") == "col1 col2"


def test_only_the_named_columns_are_touched(spark):
    df = spark.createDataFrame([("  A  ", "  B  ")], ["manufacturer", "product_name"])

    cleaned_df = normalize_whitespace(df, ["manufacturer"])

    row = cleaned_df.collect()[0]
    assert (row["manufacturer"], row["product_name"]) == ("A", "  B  ")


def test_a_null_value_stays_null(spark):
    assert cleaned(spark, None) is None
