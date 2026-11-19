"""Provision the "Spurious (counterfeit) reports" dashboard (Phase 6 step 3d).

Spurious findings are the archive's smallest slice and its most easily misread. CDSCO judges the
*pack* to be fake; the company name printed on it is a brand somebody copied, so that company is
the **victim** of the counterfeit, not its maker (CLAUDE.md §6).

Four consequences, all visible on the page:

1. **They get their own dashboard**, never a row in a manufacturer ranking. The data enforces it:
   `mart_spurious_report` carries no `manufacturer_id`, so nothing can attach these findings to a
   company even by accident.
2. **The copied brand is labelled as the copied brand** - "name printed on the pack", with the
   explanation beside it. A column titled anything like "company" would eventually be charted as
   one.
3. **The scale is stated before the charts**: 77 findings since 2024-04, out of 7,126. This
   measures what CDSCO published about counterfeits, not how much counterfeiting exists - and with
   24 months of data and single-digit monthly counts, the trend line carries almost no signal.
4. **Every row keeps its batch number, alert month and CDSCO link**, which is what makes a finding
   checkable by a person holding a pack rather than merely alarming.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/build_spurious_dashboard.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dashboards import (  # noqa: E402
    Layout,
    dashboard_url,
    ensure_chart,
    ensure_dashboard,
    ensure_datasets,
    metric,
)
from superset_api import from_env  # noqa: E402

TITLE = "Spurious (counterfeit) reports"
SLUG = "spurious-reports"

NOTE = """## Packs CDSCO reported as spurious

**Not medical advice. Data from CDSCO public alerts.**

A **spurious** finding means the pack itself was judged fake. This is different from a quality
failure, where a genuine manufacturer's batch did not meet a standard.

**The company name printed on a counterfeit pack is the brand that was copied.** That company is
the victim of the counterfeit, not its maker. Nothing on this page identifies who produced a fake
pack, because the alerts do not say - so these findings are **never counted against any
manufacturer**, here or anywhere else in this project.

**How little this is: 77 findings, from 2024-04 onwards, out of 7,126 in the archive.** Spurious
reporting is recent and sparse - single digits in most months. That makes this a record of *what
CDSCO published about counterfeits*, not a measure of how much counterfeiting exists. Please do not
read the shape of the monthly chart as a trend.

Each row below keeps its **batch number**, its **alert month** and a **link to the CDSCO
document**, so a specific pack can be checked against the original source. "Not found" never means
"guaranteed safe"."""


def main() -> None:
    superset = from_env()
    print(f"logged in to Superset at {superset.base_url}")

    print("datasets:")
    dataset = ensure_datasets(superset, ["mart_spurious_report", "mart_monthly_reporting"])

    print("charts:")
    charts = {
        "Spurious findings reported": ensure_chart(
            superset,
            "Spurious findings reported",
            dataset["mart_spurious_report"],
            "big_number_total",
            {
                "metric": metric("sample_id", "COUNT", "Spurious findings"),
                "subheader": "out of 7,126 findings in the archive, all since April 2024",
            },
        ),
        "Findings naming a copied brand": ensure_chart(
            superset,
            "Findings naming a copied brand",
            dataset["mart_spurious_report"],
            "big_number_total",
            {
                "metric": metric("name_printed_on_the_pack", "COUNT", "Copied brand recorded"),
                "subheader": "the rest name no brand at all - the alert simply did not say",
            },
        ),
        "Spurious findings per alert month": ensure_chart(
            superset,
            "Spurious findings per alert month",
            dataset["mart_monthly_reporting"],
            "echarts_timeseries_bar",
            {
                "x_axis": "alert_month_start",
                "time_grain_sqla": "P1M",
                "metrics": [metric("spurious_findings", "SUM", "Spurious findings")],
                "row_limit": 500,
                "x_axis_title": "CDSCO alert month",
                "y_axis_title": "spurious findings (single digits - not a trend)",
                "rich_tooltip": True,
            },
        ),
        "Every spurious finding": ensure_chart(
            superset,
            "Every spurious finding",
            dataset["mart_spurious_report"],
            "table",
            {
                "query_mode": "raw",
                "all_columns": [
                    "alert_month",
                    "batch_no",
                    "product_name",
                    "name_printed_on_the_pack",
                    "reported_by",
                    "source_url",
                ],
                "order_by_cols": ['["alert_month", false]'],
                "row_limit": 100,  # all 77, with room to grow before the limit bites
            },
        ),
    }

    print("dashboard:")
    layout = Layout(TITLE)
    # The note comes first and is tall: on this dashboard the explanation matters more than the
    # numbers, and a reader who sees only the charts has been misinformed.
    layout.row([(layout.markdown("note", NOTE), 12, 64)])
    layout.row(
        [
            (
                layout.chart("Spurious findings reported", charts["Spurious findings reported"]),
                6,
                28,
            ),
            (
                layout.chart(
                    "Findings naming a copied brand", charts["Findings naming a copied brand"]
                ),
                6,
                28,
            ),
        ]
    )
    layout.row(
        [
            (
                layout.chart(
                    "Spurious findings per alert month",
                    charts["Spurious findings per alert month"],
                ),
                12,
                50,
            )
        ]
    )
    layout.row([(layout.chart("Every spurious finding", charts["Every spurious finding"]), 12, 80)])
    ensure_dashboard(superset, TITLE, SLUG, layout, charts)
    print(f"\n{dashboard_url(superset, SLUG)}")


if __name__ == "__main__":
    main()
