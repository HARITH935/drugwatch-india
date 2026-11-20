"""Provision the "Manufacturer reporting" dashboard in Superset, from code.

Phase 6 step 3a. Every design choice here comes from what the exploration notebook measured
(docs/analytics-findings.md), and three of them exist to stop the dashboard from implying something
the data does not support:

1. **The findings chart never appears alone.** Findings and the number of reporting laboratories
   correlate at r = 0.964 across years, so the two sit side by side in one row and the note says
   what that means. A rising line here is surveillance growing, not quality falling.
2. **The ranking is by separate alert months, not by a score or a total.** Ten findings in one
   alert is one inspection sweep; one finding in each of ten months is a pattern that persisted.
   And "repeat offenders" (plan §8.2's name) is a verdict - CLAUDE.md §6 forbids one.
3. **The long tail sits next to the ranking.** 58% of companies appear exactly once, so a top-20
   table describes 20 companies out of 2,609; the distribution is what stops a reader treating
   that table as a list of the worst offenders.

The provisioning machinery lives in dashboards.py, shared with the other build scripts. What stays
here is the charts and the reasoning, which is the part worth reading.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/build_manufacturer_dashboard.py

Idempotent: datasets, charts and the dashboard are looked up by name and updated if they exist.
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
    metric,
)
from superset_api import from_env  # noqa: E402

TITLE = "Manufacturer reporting"
SLUG = "manufacturer-reporting"

# Shown on the dashboard itself. CLAUDE.md §6 requires the disclaimer on every page; the rest is
# the honest reading of the charts, which a reader cannot infer from the bars alone.
NOTE = """## Medicine quality reports from CDSCO alerts

**Not medical advice. Data from CDSCO public alerts.**

Each finding applies to **one specific batch** that a laboratory tested, not to the product or the
company as a whole. These are *reported* failures from a sample that was never random, so they
describe **reporting history, not quality**.

**Read the two charts below together.** The number of findings per month has risen, but so has the
number of laboratories reporting them - across years the two track each other almost exactly
(r = 0.964). What grew fastest is testing, not failure.

**A ranking is not a list of the worst companies.** 58% of the 2,609 manufacturers in this archive
appear exactly once. The table is ordered by how many *separate alert months* named a company,
because a pattern that persists across months means more than a single inspection sweep.

"Not found" never means "guaranteed safe": a batch can be absent because nobody sampled it, or
because CDSCO published no alert that month (101 of 111 months are covered)."""


def main() -> None:
    superset = from_env()
    print(f"logged in to Superset at {superset.base_url}")

    print("datasets:")
    dataset = ensure_datasets(
        superset,
        [
            "mart_monthly_reporting",
            "mart_repeat_reported_manufacturers",
            "mart_manufacturer_report_counts",
            "dim_manufacturer",
        ],
    )

    print("charts:")
    charts = {
        "Batches reported": ensure_chart(
            superset,
            "Batches reported",
            dataset["mart_monthly_reporting"],
            "big_number_total",
            {
                "metric": metric("findings", "SUM", "NSQ / spurious batches reported"),
                "subheader": "across 101 published alert months - reporting history, not quality",
            },
        ),
        "Manufacturers named": ensure_chart(
            superset,
            "Manufacturers named",
            dataset["dim_manufacturer"],
            "big_number_total",
            {
                "metric": metric("manufacturer_id", "COUNT_DISTINCT", "Manufacturers named"),
                "subheader": "58% of them appear exactly once",
            },
        ),
        "Batches reported per alert month": ensure_chart(
            superset,
            "Batches reported per alert month",
            dataset["mart_monthly_reporting"],
            "echarts_timeseries_bar",
            {
                "x_axis": "alert_month_start",
                "time_grain_sqla": "P1M",
                "metrics": [metric("findings", "SUM", "Batches reported")],
                "row_limit": 500,
                "x_axis_title": "CDSCO alert month",
                "y_axis_title": "batches reported",
                "rich_tooltip": True,
            },
        ),
        "Laboratories reporting per alert month": ensure_chart(
            superset,
            "Laboratories reporting per alert month",
            dataset["mart_monthly_reporting"],
            "echarts_timeseries",
            {
                "x_axis": "alert_month_start",
                "time_grain_sqla": "P1M",
                "metrics": [metric("reporting_labs", "SUM", "Laboratories reporting")],
                "row_limit": 500,
                "x_axis_title": "CDSCO alert month",
                "y_axis_title": "distinct laboratories named",
                "rich_tooltip": True,
            },
        ),
        "Most frequently reported manufacturers": ensure_chart(
            superset,
            "Most frequently reported manufacturers",
            dataset["mart_repeat_reported_manufacturers"],
            "table",
            {
                "query_mode": "raw",
                "all_columns": [
                    "canonical_name",
                    "state_name",
                    "alert_months_reported",
                    "reports_total",
                    "first_alert_month",
                    "last_alert_month",
                ],
                "order_by_cols": ['["alert_months_reported", false]'],
                "row_limit": 20,
            },
        ),
        "How many findings each company has": ensure_chart(
            superset,
            "How many findings each company has",
            dataset["mart_manufacturer_report_counts"],
            "table",
            {
                "query_mode": "raw",
                "all_columns": [
                    "findings_per_manufacturer",
                    "manufacturers",
                    "pct_of_manufacturers",
                    "pct_of_findings",
                ],
                "order_by_cols": ['["findings_per_manufacturer", true]'],
                "row_limit": 15,
            },
        ),
    }

    print("dashboard:")
    layout = Layout(TITLE)
    layout.row([(layout.markdown("note", NOTE + SOURCE_FOOTER), 12, 60)])
    layout.row(
        [
            (layout.chart("Batches reported", charts["Batches reported"]), 6, 30),
            (layout.chart("Manufacturers named", charts["Manufacturers named"]), 6, 30),
        ]
    )
    # One row, side by side: neither of these two may be read without the other in view.
    layout.row(
        [
            (
                layout.chart(
                    "Batches reported per alert month",
                    charts["Batches reported per alert month"],
                ),
                6,
                60,
            ),
            (
                layout.chart(
                    "Laboratories reporting per alert month",
                    charts["Laboratories reporting per alert month"],
                ),
                6,
                60,
            ),
        ]
    )
    layout.row(
        [
            (
                layout.chart(
                    "Most frequently reported manufacturers",
                    charts["Most frequently reported manufacturers"],
                ),
                7,
                70,
            ),
            (
                layout.chart(
                    "How many findings each company has",
                    charts["How many findings each company has"],
                ),
                5,
                70,
            ),
        ]
    )
    # TODO (Phase 6 step 5): the "Data last updated" panel is blocked on a corrupt dataset row in
    # Superset's metadata - gold.mart_data_freshness exists there but its own API returns 404 for
    # it, so it can neither be found nor re-created. Recorded in PROGRESS.md; the mart itself is
    # built and tested, and the source note below already points at it.
    ensure_dashboard(superset, TITLE, SLUG, layout, charts)
    print(f"\n{dashboard_url(superset, SLUG)}")


if __name__ == "__main__":
    main()
