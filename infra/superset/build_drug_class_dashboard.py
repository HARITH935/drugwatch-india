"""Provision the "What kinds of medicine are reported" dashboard (Phase 6 step 3c).

This is the only dashboard in the project built on a column the CDSCO archive does not contain,
and almost every choice here follows from that.

**Nothing in the archive classifies a medicine.** No ATC code, no therapeutic group; `generic_name`
is filled for 1,340 of 5,651 product names and holds the whole printed string rather than a
normalised salt. So `drug_classes` comes from a vocabulary of 213 ingredient phrases that Harith
accepted one batch at a time, each with a written reason, and 2 proposals he rejected (ADR 0014).
That makes every number on this page **a measurement of the archive through a reviewed lens**, not
a fact CDSCO reported - and the note says exactly that, first, before any chart.

Four things this dashboard refuses to do:

1. **It does not hide the 19.4% it cannot classify.** `Unclassified` is the largest bar on the
   chart and the first row of the table, because a reader's first question about a classification
   is how much of the data it misses. Sorting it away would have been easy and would have
   flattered the work.
2. **It never draws a pie, or anything else that implies the classes partition the data.** 530
   findings carry two to four classes, so the classes sum to 7,721 against an archive of 7,126.
   Bars and tables can carry that; a pie chart asserts the opposite.
3. **It never sums `findings` across failure categories.** `mart_drug_class_failures` (plan §8.2)
   is correct but its grain is class x category x month, where one finding can be four rows. The
   charts read `mart_drug_class_summary` and `mart_drug_class_category` instead, whose grains make
   the safe reading the default one - a dashboard should not depend on remembering a caveat.
4. **It does not present the non-therapeutic classes as medicine.** CDSCO tests cotton wool,
   gauze, syringes, hand sanitiser, soap and hair colour. Four classes exist to say so. The beauty
   creams are the sharpest case: some were tested *because* they contained steroids they should not
   have, so a `Corticosteroid` label would have inverted the finding.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/build_drug_class_dashboard.py

Idempotent. **After it runs, re-run configure_public_role.py**: it registers new datasets, and
Superset's dataset and chart list APIs filter by `datasource_access`, so an ungranted dataset is
invisible even to an admin.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dashboards import (  # noqa: E402
    SOURCE_FOOTER,
    Layout,
    dashboard_url,
    ensure_chart,
    ensure_dashboard,
    ensure_datasets,
    ensure_freshness_chart,
    metric,
)
from superset_api import from_env  # noqa: E402

TITLE = "What kinds of medicine are reported"
SLUG = "drug-classes"

NOTE = """## What kinds of medicine appear in these alerts

**Not medical advice. Data from CDSCO public alerts.**

**Read this before the charts: the drug class is not CDSCO data.** The alerts name a product, a
batch and a manufacturer. They do not say what kind of medicine it is - there is no therapeutic
class, no ATC code, and the printed name is all there is to go on. So the classes below come from
a **reviewed vocabulary of 213 ingredient names**, each one accepted by a person with its reason
recorded, applied to the name printed on the pack. They are a lens on the archive, not a fact it
reports.

**19.4% of findings (1,382) could not be classified at all**, mostly brand-named products whose
pack prints no ingredient. That is the largest single bar below, deliberately: a classification
should be judged first on what it misses.

**The classes do not add up to 100%, and they are not slices of a pie.** 530 findings name
ingredients from two to four different classes - a cough syrup is routinely four medicines in one
bottle - and each is counted under every class it contains. The classes total 7,721 against an
archive of 7,126 findings.

**Not every product here is a medicine.** CDSCO also tests absorbent cotton wool, gauze, syringes,
hand sanitiser, soap and hair colour against Indian Pharmacopoeia standards, so four of the classes
say that rather than pretending otherwise.

Each finding is still **one tested batch** of one product, not a judgement on a product or a
company, and these remain *reported* failures from a sample that was never random - so they
describe **reporting history, not quality**."""


def main() -> None:
    superset = from_env()
    print(f"logged in to Superset at {superset.base_url}")

    print("datasets:")
    dataset = ensure_datasets(
        superset,
        ["mart_drug_class_summary", "mart_drug_class_category", "mart_data_freshness"],
    )

    print("charts:")
    charts = {
        "Findings that could be classified": ensure_chart(
            superset,
            "Findings that could be classified",
            dataset["mart_drug_class_summary"],
            "big_number_total",
            {
                # MAX, not SUM: the headline is repeated on every row of the mart, the same shape
                # mart_lab_vs_maker_state uses. Summing it would multiply it by 27.
                "metric": metric("pct_classified", "MAX", "% of findings classified"),
                "subheader": "by a reviewed vocabulary of 213 ingredient names - the other 19.4% "
                "print no ingredient this could match",
            },
        ),
        "Findings with no class": ensure_chart(
            superset,
            "Findings with no class",
            dataset["mart_drug_class_summary"],
            "big_number_total",
            {
                "metric": metric("findings_unclassified", "MAX", "Unclassified findings"),
                "subheader": "mostly brand-named products whose pack prints no ingredient",
            },
        ),
        "Batches reported by kind of medicine": ensure_chart(
            superset,
            "Batches reported by kind of medicine",
            dataset["mart_drug_class_summary"],
            "echarts_timeseries_bar",
            {
                # A categorical x-axis, so no time grain: see query_context() in dashboards.py.
                "x_axis": "drug_class",
                "metrics": [metric("findings", "SUM", "Batches reported")],
                # Every class, including Unclassified and the four non-medicine ones. No row limit
                # that would cut the tail: a class left off a chart reads as a class with nothing
                # in it.
                "row_limit": 40,
                "x_axis_title": "kind of medicine (from a reviewed vocabulary, not from CDSCO)",
                "y_axis_title": "batches reported",
                # Without `x_axis_sort` naming the metric, the bars draw alphabetically and the
                # shape the chart exists to show disappears.
                "x_axis_sort": "Batches reported",
                "x_axis_sort_asc": False,
                "rich_tooltip": True,
            },
        ),
        "Each kind of medicine, and what most often failed": ensure_chart(
            superset,
            "Each kind of medicine, and what most often failed",
            dataset["mart_drug_class_summary"],
            "table",
            {
                "query_mode": "raw",
                "all_columns": [
                    "drug_class",
                    "findings",
                    "pct_of_findings",
                    "products",
                    "commonest_failure",
                    "commonest_failure_pct",
                ],
                "order_by_cols": ['["findings", false]'],
                "row_limit": 40,
            },
        ),
        "Which tests failed, within each kind of medicine": ensure_chart(
            superset,
            "Which tests failed, within each kind of medicine",
            dataset["mart_drug_class_category"],
            "table",
            {
                "query_mode": "raw",
                "all_columns": [
                    "drug_class",
                    "failure_category",
                    "mentions",
                    "findings_in_class",
                    "pct_of_class",
                ],
                # Ordered by the class's size first, so the biggest classes are at the top rather
                # than the alphabetically luckiest.
                "order_by_cols": ['["findings_in_class", false]', '["mentions", false]'],
                "row_limit": 200,
            },
        ),
    }

    print("dashboard:")
    layout = Layout(TITLE)
    layout.row([(layout.markdown("note", NOTE + SOURCE_FOOTER), 12, 78)])
    layout.row(
        [
            (
                layout.chart(
                    "Findings that could be classified",
                    charts["Findings that could be classified"],
                ),
                6,
                30,
            ),
            (layout.chart("Findings with no class", charts["Findings with no class"]), 6, 30),
        ]
    )
    layout.row(
        [
            (
                layout.chart(
                    "Batches reported by kind of medicine",
                    charts["Batches reported by kind of medicine"],
                ),
                12,
                60,
            )
        ]
    )
    layout.row(
        [
            (
                layout.chart(
                    "Each kind of medicine, and what most often failed",
                    charts["Each kind of medicine, and what most often failed"],
                ),
                6,
                70,
            ),
            (
                layout.chart(
                    "Which tests failed, within each kind of medicine",
                    charts["Which tests failed, within each kind of medicine"],
                ),
                6,
                70,
            ),
        ]
    )
    # Identical on every dashboard: a reader comparing two pages must not see two different
    # answers to "how old is this?".
    freshness_name, freshness_id = ensure_freshness_chart(superset, dataset)
    charts[freshness_name] = freshness_id
    layout.row([(layout.chart(freshness_name, freshness_id), 12, 22)])

    ensure_dashboard(superset, TITLE, SLUG, layout, charts)
    print(f"\n{dashboard_url(superset, SLUG)}")


if __name__ == "__main__":
    main()
