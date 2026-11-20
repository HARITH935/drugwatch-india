"""Provision the "Where medicines are made and tested" dashboard (Phase 6 step 3b).

This dashboard exists in an awkward shape on purpose, and the shape is the point.

"Reports by state" means two unrelated things, and the archive says so loudly: where both states
are known, the laboratory that tested a batch is in a **different state from its manufacturer in
92.7% of findings** (gold.mart_lab_vs_maker_state, computed live). West Bengal tests 1,758 findings
and makes 103, because CDSCO's central laboratory in Kolkata draws samples nationwide. Himachal
Pradesh makes 2,147 and tests 104.

So:

- **Two charts, never one.** "Made here" and "tested here" are separate charts with separate
  titles. A single chart, or either number alone, would be read as "unsafe medicine in this state".
- **They are never added together.** Adding them would double-count every finding whose maker and
  laboratory happen to share a state, and mean nothing for the other 92.7%.
- **No map of India.** Two reasons, and either is enough: India's boundary depiction is legally
  sensitive for a public site serving Indian users, and Superset's bundled GeoJSON may predate the
  2019 Jammu & Kashmir / Ladakh reorganisation and the 2020 Dadra & Nagar Haveli merger. A bar
  chart carries the same information and makes no territorial claim (decision D, 2026-11-19).
- **The state-laboratory subset is given its own column.** A state laboratory tests its own state's
  samples, so `state_lab_reports_tested_here` is the only honest answer to "what was found in this
  state's own testing" - and it is far smaller than the headline.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/build_states_dashboard.py
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

TITLE = "Where medicines are made and tested"
SLUG = "states"

NOTE = """## Two different questions about states

**Not medical advice. Data from CDSCO public alerts.**

A finding has two states attached, and they are **not the same thing**:

- **Made here** - the state the manufacturer is in. This says something about where a flagged batch
  came from.
- **Tested here** - the state of the laboratory that tested it. This says where the *laboratories*
  are. CDSCO's central laboratories draw samples from the whole country.

**In 92.7% of findings where both are known, they are different states.** West Bengal tests
1,758 findings and makes 103; Himachal Pradesh makes 2,147 and tests 104.

So the two charts below are kept apart, and **their numbers must never be added together** - that
would double-count the few findings where maker and laboratory share a state, and misrepresent
every other one. If you want "what did this state's own laboratories find?", use the
*tested by a state laboratory* column in the table, which is much smaller than the headline.

There is **no map** here. India's boundaries are legally sensitive to depict, and a bar chart
carries the same information without making a territorial claim. 603 of 2,609 manufacturers have no
resolvable state at all, so they appear in no bar on this page."""


def main() -> None:
    superset = from_env()
    print(f"logged in to Superset at {superset.base_url}")

    print("datasets:")
    dataset = ensure_datasets(
        superset,
        ["mart_state_summary", "mart_lab_vs_maker_state", "mart_data_freshness"],
    )

    print("charts:")
    charts = {
        "Findings tested in a different state from the maker": ensure_chart(
            superset,
            "Findings tested in a different state from the maker",
            dataset["mart_lab_vs_maker_state"],
            "big_number_total",
            {
                "metric": metric(
                    "pct_tested_in_a_different_state", "MAX", "% tested in another state"
                ),
                "subheader": "of the 75.7% of findings where both states are known - which is why "
                "'made here' and 'tested here' are separate charts",
            },
        ),
        "Batches made in each state": ensure_chart(
            superset,
            "Batches made in each state",
            dataset["mart_state_summary"],
            "echarts_timeseries_bar",
            {
                # A categorical x-axis, so no time grain: see query_context() in dashboards.py.
                "x_axis": "state_name",
                "metrics": [metric("reports_made_here", "SUM", "Batches reported, made here")],
                "row_limit": 15,
                "x_axis_title": "manufacturing state",
                "y_axis_title": "batches reported",
                # Sort the bars by value, biggest first. Without `x_axis_sort` naming the metric,
                # the 15 states the query returns (correctly, the 15 largest) are drawn in
                # alphabetical order, which hides the shape the chart exists to show.
                "x_axis_sort": "Batches reported, made here",
                "x_axis_sort_asc": False,
                "rich_tooltip": True,
            },
        ),
        "Batches tested in each state": ensure_chart(
            superset,
            "Batches tested in each state",
            dataset["mart_state_summary"],
            "echarts_timeseries_bar",
            {
                "x_axis": "state_name",
                "metrics": [metric("reports_tested_here", "SUM", "Batches tested here")],
                "row_limit": 15,
                "x_axis_title": "state of the testing laboratory (NOT where the medicine was made)",
                "y_axis_title": "batches tested",
                # Sort the bars by value, biggest first. Without `x_axis_sort` naming the metric,
                # the 15 states the query returns (correctly, the 15 largest) are drawn in
                # alphabetical order, which hides the shape the chart exists to show.
                "x_axis_sort": "Batches tested here",
                "x_axis_sort_asc": False,
                "rich_tooltip": True,
            },
        ),
        "Made here, tested here, side by side": ensure_chart(
            superset,
            "Made here, tested here, side by side",
            dataset["mart_state_summary"],
            "table",
            {
                "query_mode": "raw",
                "all_columns": [
                    "state_name",
                    "state_type",
                    "reports_made_here",
                    "manufacturers_here",
                    "reports_tested_here",
                    "state_lab_reports_tested_here",
                ],
                "order_by_cols": ['["reports_made_here", false]'],
                "row_limit": 36,  # every state and union territory, including the zeros
            },
        ),
    }

    print("dashboard:")
    layout = Layout(TITLE)
    layout.row([(layout.markdown("note", NOTE + SOURCE_FOOTER), 12, 62)])
    layout.row(
        [
            (
                layout.chart(
                    "Findings tested in a different state from the maker",
                    charts["Findings tested in a different state from the maker"],
                ),
                12,
                28,
            )
        ]
    )
    # Same row, same size: the two meanings are presented as equals, and neither can be seen
    # without the other.
    made = layout.chart("Batches made in each state", charts["Batches made in each state"])
    tested = layout.chart("Batches tested in each state", charts["Batches tested in each state"])
    layout.row([(made, 6, 60), (tested, 6, 60)])
    layout.row(
        [
            (
                layout.chart(
                    "Made here, tested here, side by side",
                    charts["Made here, tested here, side by side"],
                ),
                12,
                75,
            )
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
