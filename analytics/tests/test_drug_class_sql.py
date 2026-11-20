"""The two implementations of one match rule must agree (ADR 0014).

The rule - "this ingredient phrase appears as a whole word in this product name" - exists twice,
and not by accident. The review has to run before `int_drug_class` can exist, so it needs the rule
in Python; dbt needs it in SQL to build the warehouse. Two copies of a rule drift, and the drift
would be invisible: the dashboard would simply disagree with the review that produced it.

So this compares them over every product name in the archive and requires identical answers. It
is the only guard on that, and it is why the vocabulary is restricted to plain text that means the
same thing to both regex engines.
"""

import csv
from pathlib import Path

import pytest

from drugwatch_analytics.drug_class import classes_for

SEED = Path(__file__).resolve().parents[2] / "dbt" / "seeds" / "drug_class_vocabulary.csv"


def seed_vocabulary() -> dict[str, str]:
    """Read the committed seed, not the proposals: what dbt built from is what must agree."""
    with SEED.open() as handle:
        return {row["ingredient"]: row["drug_class"] for row in csv.DictReader(handle)}


def test_the_seed_only_holds_entries_a_person_accepted():
    """215 were proposed; the seed must not quietly contain the ones that were rejected."""
    from drugwatch_analytics.drug_class_review import accepted_vocabulary

    accepted = accepted_vocabulary()
    if not accepted:
        pytest.skip("no review decisions on this machine (data/ is git-ignored)")
    assert seed_vocabulary() == accepted


def test_the_seed_carries_no_counts_from_the_archive():
    """A measurement in here would make a pharmacological claim look like a CDSCO one."""
    with SEED.open() as handle:
        assert next(csv.reader(handle)) == ["ingredient", "drug_class"]


@pytest.mark.integration
def test_sql_and_python_match_the_same_products(gold_available):
    """The real check: every product name, both engines, no disagreement allowed."""
    from drugwatch_analytics.gold import query

    vocabulary = seed_vocabulary()
    rows = query("select product_name, drug_classes from gold.dim_drug")

    disagreements = []
    for product_name, from_sql in zip(rows["product_name"], rows["drug_classes"], strict=True):
        # dim_drug sorts the array; classes_for returns CLASSES order, so compare as sets.
        from_python = set(classes_for(product_name, vocabulary))
        if set(from_sql) != from_python:
            disagreements.append((product_name, sorted(from_sql), sorted(from_python)))

    assert not disagreements, (
        f"{len(disagreements)} product name(s) classified differently by SQL and Python, "
        f"first three: {disagreements[:3]}"
    )


@pytest.mark.integration
def test_the_unclassified_remainder_is_an_empty_array_not_a_null(gold_available):
    """A null would make every consumer handle a third case that does not exist, and it is the
    difference between "no class matched" and "not computed"."""
    from drugwatch_analytics.gold import query

    nulls = query("select count(*) as n from gold.dim_drug where drug_classes is null")
    assert int(nulls.iloc[0]["n"]) == 0
    empty = query("select count(*) as n from gold.dim_drug where cardinality(drug_classes) = 0")
    assert int(empty.iloc[0]["n"]) > 0, "something matched every single product name - suspicious"


@pytest.mark.integration
def test_the_mart_keeps_every_finding_including_the_unclassified_ones(gold_available):
    """The mart left-joins the unnest so an unclassified finding is still counted. If that became
    an inner join, roughly a fifth of the archive would vanish and every percentage on the
    dashboard would silently change its denominator."""
    from drugwatch_analytics.gold import query

    totals = query(
        """
        select
            (select count(*) from gold.fact_nsq_sample) as findings,
            (select count(distinct drug_class) from gold.mart_drug_class_failures) as classes,
            (select sum(findings) from gold.mart_drug_class_failures
             where drug_class = 'Unclassified') as unclassified_pairs
        """
    )
    row = totals.iloc[0]
    assert int(row["classes"]) == 27, "26 vocabulary classes plus Unclassified"
    assert int(row["unclassified_pairs"]) > 0


@pytest.mark.integration
def test_summing_the_mart_overcounts_and_the_model_says_so(gold_available):
    """Not a bug - the documented consequence of two arrays. This test exists so that anyone who
    'fixes' the double counting has to come here and read why it is intended."""
    from drugwatch_analytics.gold import query

    row = query(
        """
        select
            sum(findings) as naive_sum,
            (select count(*) from gold.fact_nsq_sample) as real_total
        from gold.mart_drug_class_failures
        """
    ).iloc[0]
    assert int(row["naive_sum"]) > int(row["real_total"]), (
        "a finding with two classes and two failure categories is four rows here; if this ever "
        "stops being true, the mart's grain changed and its warning needs rewriting"
    )
