"""Make a chart-less dashboard visible again, so its build script can take over.

Superset decides who may see a dashboard from the **datasources of the charts on it**. A dashboard
with no charts therefore satisfies nothing and is invisible even to an admin: the dashboard API
omits it, while its slug stays taken, so a build script can neither find it nor create it.

Measured here on 2026-11-20, and this is how it happens: a build script creates the dashboard,
then fails while attaching the charts - a newly registered dataset with no `datasource_access`
grant is the usual reason - and leaves the dashboard behind with nothing on it.

Attaching any one chart is enough to bring it back, because the chart API is not filtered the same
way and can reach a dashboard the dashboard API cannot. After that the build script's normal
update path works and gives the dashboard its real contents.

Which dashboards are hidden comes from **Superset's own metadata database**, not from guessing ids
against the API: probing ids one by one trips Superset's rate limiter (50 requests/second) and
cannot tell "no such dashboard" from "throttled", which would make a hidden dashboard look absent.

Run from the repo root, with the stack up and `.env` loaded:
    set -a && . ./.env && set +a && python3 infra/superset/attach_orphan_dashboard.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from superset_api import from_env  # noqa: E402


def dashboards_in_the_database() -> dict[int, str]:
    """id -> title, straight from Superset's metadata, bypassing the API's access filter."""
    # S607 (partial executable path) is accepted deliberately: `docker` is resolved from PATH,
    # exactly as every other command in this repo's docs invokes it, and hardcoding an absolute
    # path would break on any machine that installed Docker elsewhere.
    command = [  # noqa: S607
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "drugwatch",
        "-d",
        "superset",
        "-t",
        "-A",
        "-F",
        "\t",
        "-c",
        "select id, dashboard_title from dashboards order by id",
    ]
    result = subprocess.run(  # noqa: S603 - fixed argv, never a shell string
        command,
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    found = {}
    for line in result.stdout.splitlines():
        if "\t" in line:
            dashboard_id, title = line.split("\t", 1)
            found[int(dashboard_id)] = title
    return found


def main() -> int:
    superset = from_env()

    charts = superset.get("/api/v1/chart/?q=(page_size:100)")["result"]
    if not charts:
        print("Superset has no charts its API can see, so there is nothing to attach with.")
        print("Grant datasource access first: configure_public_role.py")
        return 1

    in_api = {
        board["id"] for board in superset.get("/api/v1/dashboard/?q=(page_size:100)")["result"]
    }
    in_database = dashboards_in_the_database()
    hidden = sorted(set(in_database) - in_api)

    print(f"in the database: {sorted(in_database)}; visible to the API: {sorted(in_api)}")
    if not hidden:
        print("nothing is hidden - no dashboard needs rescuing.")
        return 0

    anchor = charts[0]["id"]
    for dashboard in hidden:
        print(f"hidden: {dashboard} ({in_database[dashboard]}) - attaching chart {anchor}")
        current = superset.get(f"/api/v1/chart/{anchor}")["result"]
        memberships = {board["id"] for board in current.get("dashboards", [])} | {dashboard}
        superset.put(f"/api/v1/chart/{anchor}", {"dashboards": sorted(memberships)})

    now = {board["id"] for board in superset.get("/api/v1/dashboard/?q=(page_size:100)")["result"]}
    still_hidden = sorted(set(in_database) - now)
    if still_hidden:
        print(f"STILL hidden: {still_hidden} - attaching a chart did not fix it, so the cause")
        print("is something other than an empty dashboard. Do not guess; investigate.")
        return 1
    print(f"recovered {hidden}; now re-run that dashboard's build script to fill it in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
