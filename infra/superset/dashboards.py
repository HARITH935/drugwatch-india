"""Shared machinery for provisioning dashboards from code.

Extracted when the second dashboard needed the same pieces as the first. Copying them would have
let the two drift: a fix to one dashboard's chart handling would silently not apply to the other,
which is the same argument that put Phase 5's pipeline chain in one place.

What lives here: how a dataset is registered, how a metric is written, how a chart is created
(including the `query_context` Superset's UI saves and the API does not), and how a dashboard's
grid is assembled. What stays in each `build_*_dashboard.py`: the charts themselves and the
reasoning behind them, which is the part worth reading.
"""

import json
import urllib.parse
from typing import Any

from superset_api import Superset

DATABASE_NAME = "DrugWatch gold"
SCHEMA = "gold"


# --- datasets and metrics ------------------------------------------------------------------------


def database_id(superset: Superset) -> int:
    found = superset.find_id("database", "database_name", DATABASE_NAME)
    if not found:
        raise SystemExit(f"no '{DATABASE_NAME}' connection - run register_gold_database.sh first")
    return found


def ensure_dataset(superset: Superset, database: int, table: str) -> int:
    """The dataset id for a gold table, creating it if Superset does not know it yet."""
    existing = superset.find_id("dataset", "table_name", table)
    if existing:
        return existing
    answer = superset.post(
        "/api/v1/dataset/", {"database": database, "schema": SCHEMA, "table_name": table}
    )
    print(f"  dataset created: {table} (id {answer['id']})")
    return answer["id"]


def ensure_datasets(superset: Superset, tables: list[str]) -> dict[str, int]:
    database = database_id(superset)
    return {table: ensure_dataset(superset, database, table) for table in tables}


def metric(column: str, aggregate: str, label: str) -> dict[str, Any]:
    """An "adhoc" metric: an aggregate defined in the chart rather than on the dataset.

    Keeps each dataset a plain mirror of its gold table. The marts already did the aggregating
    that matters; these are SUM/COUNT over columns the marts computed.
    """
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": aggregate,
        "label": label,
        "optionName": f"metric_{column}_{aggregate.lower()}",
    }


# --- charts ---------------------------------------------------------------------------------------


def query_context(params: dict[str, Any], dataset_id: int, viz_type: str) -> dict[str, Any]:
    """The query Superset will run for this chart, stored alongside its parameters.

    Superset's UI saves two things when a chart is saved: `params` (what the controls say) and
    `query_context` (the query those controls produce). A chart created over the API with only
    `params` is accepted, renders in a browser - and fails anything that asks it for data
    server-side, with "Chart has no query context saved". In Phase 9 that would include alerts and
    reports, and here it would mean no way to verify a chart without a browser.
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

    else:  # the echarts family, time-based or categorical
        axis = params["x_axis"]
        grain = params.get("time_grain_sqla")
        label = params["metrics"][0]["label"]
        axis_column: dict[str, Any] = {
            "columnType": "BASE_AXIS",
            "sqlExpression": axis,
            "label": axis,
            "expressionType": "SQL",
        }
        extras = {"having": "", "where": ""}
        if grain:
            # Only a date axis has a time grain. Setting one on a text column (a state name) makes
            # Postgres try to truncate a string to a month.
            axis_column["timeGrain"] = grain
            extras["time_grain_sqla"] = grain
        query = {
            **base_query,
            "columns": [axis_column],
            "metrics": params["metrics"],
            "orderby": [[params["metrics"][0], False]],
            "extras": extras,
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
    superset: Superset, name: str, dataset_id: int, viz_type: str, params: dict[str, Any]
) -> int:
    """Create or update a chart by name. Returns its id."""
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


# --- dashboards -----------------------------------------------------------------------------------


class Layout:
    """Builds the grid JSON Superset stores for a dashboard.

    Rows of 12 columns, added in reading order - which matters here, because the order is the
    argument each dashboard is making. Nothing about this is clever; it exists because the raw
    format is verbose and easy to get subtly wrong.
    """

    def __init__(self, title: str) -> None:
        self.position: dict[str, Any] = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
            "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": []},
            "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": title}},
        }
        self._parents = ["ROOT_ID", "GRID_ID"]
        self._rows = 0

    def markdown(self, key: str, text: str) -> str:
        node_id = f"MARKDOWN-{key}"
        self.position[node_id] = {
            "type": "MARKDOWN",
            "id": node_id,
            "children": [],
            "meta": {"code": text},
        }
        return node_id

    def chart(self, name: str, chart_id: int) -> str:
        node_id = f"CHART-{name}"
        self.position[node_id] = {
            "type": "CHART",
            "id": node_id,
            "children": [],
            "meta": {"chartId": chart_id, "sliceName": name},
        }
        return node_id

    def row(self, items: list[tuple[str, int, int]]) -> None:
        """items: (node_id, width out of 12, height)."""
        self._rows += 1
        row_id = f"ROW-{self._rows}"
        self.position["GRID_ID"]["children"].append(row_id)
        self.position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "parents": self._parents,
            "children": [item[0] for item in items],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for node_id, width, height in items:
            self.position[node_id]["parents"] = [*self._parents, row_id]
            self.position[node_id]["meta"].update({"width": width, "height": height})


def ensure_dashboard(
    superset: Superset, title: str, slug: str, layout: Layout, charts: dict[str, int]
) -> int:
    """Create or update a dashboard, and make its charts aware they belong to it."""
    payload = {
        "dashboard_title": title,
        "slug": slug,
        "position_json": json.dumps(layout.position),
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
    existing = superset.find_id("dashboard", "dashboard_title", title)
    if existing:
        superset.put(f"/api/v1/dashboard/{existing}", payload)
        dashboard = existing
        print(f"  dashboard updated: {title} (id {dashboard})")
    else:
        dashboard = superset.post("/api/v1/dashboard/", payload)["id"]
        print(f"  dashboard created: {title} (id {dashboard})")

    # A chart that renders on a dashboard but does not know it belongs there shows up as
    # "orphaned" in Superset's listings - and an orphaned chart is the first thing a cleanup
    # deletes. Existing memberships are kept, so a chart can appear on two dashboards.
    for chart_id in charts.values():
        current = superset.get(f"/api/v1/chart/{chart_id}")["result"]
        memberships = {board["id"] for board in current.get("dashboards", [])} | {dashboard}
        superset.put(f"/api/v1/chart/{chart_id}", {"dashboards": sorted(memberships)})

    return dashboard


def dashboard_url(superset: Superset, slug: str) -> str:
    return f"{superset.base_url}/superset/dashboard/{urllib.parse.quote(slug)}/"
