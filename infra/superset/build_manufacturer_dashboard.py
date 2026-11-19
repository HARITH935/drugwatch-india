"""Provision the "Manufacturer reporting" dashboard in Superset, from code.

Phase 6 step 3a. Every design choice here comes from what the exploration notebook measured
(docs/analytics-findings.md), and three of them exist to stop the dashboard from implying something
the data does not support:

1. **The findings line never appears alone.** Findings and the number of reporting laboratories
   correlate at r = 0.964 across years, so the two charts sit side by side and the markdown tile
   says what that means. A rising line here is surveillance growing, not quality falling.
2. **The ranking is by separate alert months, not by a score or a total.** Ten findings in one
   alert is one inspection sweep; one finding in each of ten months is a pattern that persisted.
   And "repeat offenders" (plan §8.2's name) is a verdict - CLAUDE.md §6 forbids one.
3. **The long tail sits next to the ranking.** 58% of companies appear exactly once, so a top-20
   table describes 20 companies out of 2,609; the distribution chart is what stops a reader
   treating that table as a list of the worst offenders.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/build_manufacturer_dashboard.py

Idempotent: datasets, charts and the dashboard are looked up by name and updated if they exist.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from superset_api import Superset, from_env  # noqa: E402

DATABASE_NAME = "DrugWatch gold"
SCHEMA = "gold"
DASHBOARD_TITLE = "Manufacturer reporting"
DATASETS = [
    "mart_monthly_reporting",
    "mart_repeat_reported_manufacturers",
    "mart_manufacturer_report_counts",
    "dim_manufacturer",
]

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
appear exactly once. The table below is ordered by how many *separate alert months* named a
company, because a pattern that persists over months means more than one inspection sweep.

"Not found" never means "guaranteed safe": a batch can be absent because nobody sampled it, or
because CDSCO published no alert that month (101 of 111 months are covered)."""


def ensure_dataset(superset: Superset, database_id: int, table: str) -> int:
    """The dataset id for a gold table, creating it if Superset does not know it yet."""
    existing = superset.find_id("dataset", "table_name", table)
    if existing:
        print(f"  dataset exists: {table} (id {existing})")
        return existing
    answer = superset.post(
        "/api/v1/dataset/",
        {"database": database_id, "schema": SCHEMA, "table_name": table},
    )
    print(f"  dataset created: {table} (id {answer['id']})")
    return answer["id"]


def metric(column: str, aggregate: str, label: str) -> dict[str, Any]:
    """An "adhoc" metric: an aggregate defined in the chart rather than on the dataset.

    Keeps the dataset a plain mirror of the gold table. The marts already did the aggregating that
    matters; these are just SUM/COUNT over their columns.
    """
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": aggregate,
        "label": label,
        "optionName": f"metric_{column}_{aggregate.lower()}",
    }


def query_context(params: dict[str, Any], dataset_id: int, viz_type: str) -> dict[str, Any]:
    """The query Superset will run for this chart, stored alongside its parameters.

    Superset's UI saves two things when you save a chart: `params` (what the controls say) and
    `query_context` (the query those controls produce). A chart created over the API with only
    `params` is accepted, renders in a browser - and fails anything that asks it for data
    server-side, with "Chart has no query context saved". That includes this project's own
    verification, and in Phase 9 it would include alerts and reports.

    So the context is built here, in the three shapes these charts need. The alternative - trusting
    that a chart with plausible parameters works - is exactly the assumption the verification step
    exists to remove.
    """
    base_query: dict[str, Any] = {
        "filters": [],
        "extras": {"having": "", "where": ""},
        "applied_time_extras": {},
        "annotation_layers": [],
        "series_limit": 0,
        "order_desc": True,
        "url_params": {},
        "custom_params": {},
        "custom_form_data": {},
        "row_limit": params.get("row_limit", 50_000),
    }

    if viz_type == "big_number_total":
        query = {
            **base_query,
            "metrics": [params["metric"]],
            "columns": [],
            "orderby": [],
            "post_processing": [],
        }

    elif viz_type == "table":
        # Raw mode: no aggregation, just the columns the mart already computed.
        query = {
            **base_query,
            "columns": params["all_columns"],
            "metrics": None,
            "orderby": [json.loads(expression) for expression in params.get("order_by_cols", [])],
            "post_processing": [],
        }

    else:  # the echarts timeseries family
        axis = params["x_axis"]
        grain = params.get("time_grain_sqla", "P1M")
        label = params["metrics"][0]["label"]
        query = {
            **base_query,
            "columns": [
                {
                    "timeGrain": grain,
                    "columnType": "BASE_AXIS",
                    "sqlExpression": axis,
                    "label": axis,
                    "expressionType": "SQL",
                }
            ],
            "metrics": params["metrics"],
            "orderby": [[params["metrics"][0], False]],
            "extras": {"having": "", "where": "", "time_grain_sqla": grain},
            "series_columns": [],
            # What Superset does to the rows before the chart draws them: one column per series.
            "post_processing": [
                {
                    "operation": "pivot",
                    "options": {
                        "index": [axis],
                        "columns": [],
                        "aggregates": {label: {"operator": "mean"}},
                        "drop_missing_columns": False,
                    },
                },
                {"operation": "flatten"},
            ],
        }

    return {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": False,
        "queries": [query],
        "form_data": {**params, "viz_type": viz_type, "datasource": f"{dataset_id}__table"},
        "result_format": "json",
        "result_type": "full",
    }


def ensure_chart(
    superset: Superset, name: str, dataset_id: int, viz_type: str, params: dict
) -> int:
    """Create or update a chart. Returns its id."""
    payload = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "params": json.dumps(
            {**params, "viz_type": viz_type, "datasource": f"{dataset_id}__table"}
        ),
        "query_context": json.dumps(query_context(params, dataset_id, viz_type)),
    }
    existing = superset.find_id("chart", "slice_name", name)
    if existing:
        superset.put(f"/api/v1/chart/{existing}", payload)
        print(f"  chart updated: {name} (id {existing})")
        return existing
    answer = superset.post("/api/v1/chart/", payload)
    print(f"  chart created: {name} (id {answer['id']})")
    return answer["id"]


def layout(charts: dict[str, int]) -> dict[str, Any]:
    """The dashboard's grid, as Superset stores it.

    Rows of 12 columns. The order is the argument the dashboard is making: the note first, then the
    two time charts side by side (so neither can be read alone), then the ranking beside the
    distribution that qualifies it.
    """
    position: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": []},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}},
    }
    parents = ["ROOT_ID", "GRID_ID"]

    def add_row(row_id: str, items: list[tuple[str, int, int]]) -> None:
        """items: (child_id, width, height) in a 12-column row."""
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "parents": parents,
            "children": [item[0] for item in items],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for child_id, width, height in items:
            node = position[child_id]
            node["parents"] = [*parents, row_id]
            node["meta"].update({"width": width, "height": height})

    position["MARKDOWN-note"] = {
        "type": "MARKDOWN",
        "id": "MARKDOWN-note",
        "children": [],
        "meta": {"code": NOTE},
    }
    for label, chart_id in charts.items():
        position[f"CHART-{label}"] = {
            "type": "CHART",
            "id": f"CHART-{label}",
            "children": [],
            "meta": {"chartId": chart_id, "sliceName": label},
        }

    add_row("ROW-note", [("MARKDOWN-note", 12, 60)])
    add_row("ROW-totals", [("CHART-Batches reported", 6, 30), ("CHART-Manufacturers named", 6, 30)])
    add_row(
        "ROW-time",
        [
            ("CHART-Batches reported per alert month", 6, 60),
            ("CHART-Laboratories reporting per alert month", 6, 60),
        ],
    )
    add_row(
        "ROW-ranking",
        [
            ("CHART-Most frequently reported manufacturers", 7, 70),
            ("CHART-How many findings each company has", 5, 70),
        ],
    )
    return position


def main() -> None:
    superset = from_env()
    print(f"logged in to Superset at {superset.base_url}")

    database_id = superset.find_id("database", "database_name", DATABASE_NAME)
    if not database_id:
        raise SystemExit(f"no '{DATABASE_NAME}' connection - run register_gold_database.sh first")

    print("datasets:")
    dataset = {table: ensure_dataset(superset, database_id, table) for table in DATASETS}

    print("charts:")
    charts: dict[str, int] = {}

    charts["Batches reported"] = ensure_chart(
        superset,
        "Batches reported",
        dataset["mart_monthly_reporting"],
        "big_number_total",
        {
            "metric": metric("findings", "SUM", "NSQ / spurious batches reported"),
            "subheader": "across 101 published CDSCO alert months - reporting history, not quality",
        },
    )
    charts["Manufacturers named"] = ensure_chart(
        superset,
        "Manufacturers named",
        dataset["dim_manufacturer"],
        "big_number_total",
        {
            "metric": metric(
                "manufacturer_id", "COUNT_DISTINCT", "Manufacturers named in an alert"
            ),
            "subheader": "58% of them appear exactly once",
        },
    )
    charts["Batches reported per alert month"] = ensure_chart(
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
    )
    charts["Laboratories reporting per alert month"] = ensure_chart(
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
    )
    charts["Most frequently reported manufacturers"] = ensure_chart(
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
            "column_config": {
                "alert_months_reported": {"columnWidth": 120},
            },
        },
    )
    charts["How many findings each company has"] = ensure_chart(
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
    )

    print("dashboard:")
    payload = {
        "dashboard_title": DASHBOARD_TITLE,
        "slug": "manufacturer-reporting",
        "position_json": json.dumps(layout(charts)),
        "published": True,
        "json_metadata": json.dumps(
            {
                # The warehouse is rebuilt monthly, so auto-refresh would only add noise.
                "refresh_frequency": 0,
                "color_scheme": "supersetColors",
                "chart_configuration": {},
            }
        ),
    }
    existing = superset.find_id("dashboard", "dashboard_title", DASHBOARD_TITLE)
    if existing:
        superset.put(f"/api/v1/dashboard/{existing}", payload)
        dashboard_id = existing
        print(f"  dashboard updated (id {dashboard_id})")
    else:
        dashboard_id = superset.post("/api/v1/dashboard/", payload)["id"]
        print(f"  dashboard created (id {dashboard_id})")

    # Charts have to know which dashboard they belong to, or they render on it but are "orphaned"
    # in Superset's own listings - and an orphaned chart is the first thing a cleanup deletes.
    for chart_id in charts.values():
        superset.put(f"/api/v1/chart/{chart_id}", {"dashboards": [dashboard_id]})

    print(f"\n{superset.base_url}/superset/dashboard/manufacturer-reporting/")


if __name__ == "__main__":
    main()
