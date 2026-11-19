"""Ask every chart in Superset for its data, and fail if any of them cannot answer.

Provisioning a chart over the API proves only that Superset accepted the parameters. A chart with a
misspelled column, a metric on a column that is not there, or a time axis that is not a date is
created happily and then fails the moment a browser asks it to render - which, on a public
dashboard, is a blank rectangle nobody notices until a visitor reports it.

So this runs each chart's own query the way the browser does, and reports the row count.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/verify_charts.py
Exit code 0 means every chart returned data without error.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from superset_api import SupersetError, from_env  # noqa: E402


def main() -> int:
    superset = from_env()
    charts = superset.get("/api/v1/chart/?q=(page_size:100)")["result"]
    if not charts:
        print("no charts exist yet - run a build_*_dashboard.py script first")
        return 1

    failures = 0
    print(f"asking {len(charts)} chart(s) for their data\n")
    for chart in sorted(charts, key=lambda c: c["slice_name"]):
        name = chart["slice_name"]
        try:
            answer = superset.chart_data(chart["id"])
            results = answer.get("result", [])
            rows = results[0].get("rowcount", 0) if results else 0
            # A chart that errors server-side still returns HTTP 200 with the error inside.
            errors = [message for result in results for message in (result.get("error") or [])]
            if errors or (results and results[0].get("status") == "failed"):
                print(f"FAIL  {name:48} {str(errors)[:60]}")
                failures += 1
            elif rows == 0:
                # Not an error, but worth failing on here: every chart in this project is built on
                # a mart that has rows, so an empty chart means the query is asking the wrong thing.
                print(f"FAIL  {name:48} returned 0 rows")
                failures += 1
            else:
                columns = len(results[0].get("colnames") or [])
                print(f"ok    {name:48} {rows:>5} rows x {columns} columns")
        except SupersetError as error:
            print(f"FAIL  {name:48} {str(error)[:70]}")
            failures += 1

    print()
    if failures:
        print(f"{failures} chart(s) cannot render")
    else:
        print("every chart returned data")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
