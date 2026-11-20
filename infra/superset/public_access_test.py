"""Check what a stranger with no login can and cannot do on this Superset.

Phase 6 step 4's done-when is "dashboards are viewable publicly with filters working". That is two
claims, and the second half of it - what a visitor *cannot* do - is the half that matters once this
is on the internet in Phase 12.

So this sends every request with **no credentials at all**: no login, no bearer token, no session
from an earlier login. Whatever it can reach is what the public can reach.

Run from the repo root, with the stack up:
    python3 infra/superset/public_access_test.py
Exit code 0 means every expectation held.
"""

import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE_URL = "http://localhost:8088"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Report a redirect instead of following it.

    Flask-AppBuilder protects its admin pages by redirecting an anonymous visitor to /login/. With
    redirects followed, `/users/list/` came back as HTTP 200 - the login page - and this test read
    that as "a stranger can list users". The endpoint was fine; the test was lying. Not following
    redirects makes "you must log in" visible as a 302, which is what it is.
    """

    def redirect_request(self, *args, **kwargs):  # noqa: ARG002
        return None


# One cookie jar, no Authorization header, ever: this is a browser that has never logged in.
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), NoRedirects)


def call(method: str, path: str, payload: dict | None = None, csrf: str = "") -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{BASE_URL}{path}", data=data, method=method)  # noqa: S310
    request.add_header("Content-Type", "application/json")
    if csrf:
        request.add_header("X-CSRFToken", csrf)
        request.add_header("Referer", BASE_URL)
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()
    except urllib.error.URLError as error:
        return 0, str(error)


def main() -> int:
    failures = 0

    def expect(description: str, allowed: bool, status: int, detail: str = "") -> None:
        nonlocal failures
        ok = (200 <= status < 400) if allowed else status in (401, 403, 302, 404)
        verdict = "ok   " if ok else "FAIL "
        if not ok:
            failures += 1
        wanted = "readable" if allowed else "refused"
        print(f"{verdict} {description:52} HTTP {status:<4} ({wanted}) {detail}")

    print("== what an anonymous visitor can reach ==")

    # Anonymous visitors need a CSRF token to POST anything, which is itself a permission.
    status, body = call("GET", "/api/v1/security/csrf_token/")
    csrf = json.loads(body)["result"] if status == 200 else ""
    expect("fetch a CSRF token", True, status)

    status, _ = call("GET", "/api/v1/dashboard/")
    expect("list dashboards", True, status)

    for slug in ("manufacturer-reporting", "states", "spurious-reports"):
        status, _ = call("GET", f"/superset/dashboard/{slug}/")
        expect(f"open the {slug} dashboard", True, status)

    # The real test of "viewable": can an anonymous visitor run a chart's query and get numbers?
    status, body = call("GET", "/api/v1/chart/?q=(page_size:1)")
    expect("list charts", True, status)
    chart_id = json.loads(body)["result"][0]["id"] if status == 200 else None

    if chart_id:
        status, body = call("GET", f"/api/v1/chart/{chart_id}")
        context = json.loads(body)["result"].get("query_context") if status == 200 else None
        if context:
            status, body = call("POST", "/api/v1/chart/data", json.loads(context), csrf)
            rows = ""
            if status == 200:
                results = json.loads(body).get("result", [{}])
                rows = f"{results[0].get('rowcount', 0)} rows"
            expect("run a chart's query (the charts fill with data)", True, status, rows)

    # Filters: Superset stores a visitor's selections server-side, so "filters working" requires
    # this write to succeed. It writes transient state keyed to this visitor only.
    status, _ = call(
        "POST", "/api/v1/dashboard/1/filter_state", {"value": '{"test": "filter state"}'}, csrf
    )
    expect("save filter state (filters working)", True, status)

    print("\n== what an anonymous visitor must NOT be able to do ==")

    status, _ = call("POST", "/api/v1/chart/", {"slice_name": "anonymous was here"}, csrf)
    expect("create a chart", False, status)

    status, _ = call(
        "PUT", "/api/v1/dashboard/1", {"dashboard_title": "defaced by anonymous"}, csrf
    )
    expect("rename a dashboard", False, status)

    status, _ = call("DELETE", "/api/v1/dashboard/1", csrf=csrf)
    expect("delete a dashboard", False, status)

    status, _ = call(
        "POST",
        "/api/v1/sqllab/execute/",
        {"database_id": 1, "sql": "select 1", "runAsync": False},
        csrf,
    )
    expect("run arbitrary SQL (SQL Lab)", False, status)

    status, _ = call("GET", "/api/v1/database/")
    expect("list database connections", False, status)

    status, _ = call("GET", "/api/v1/security/roles/")
    expect("read the role configuration", False, status)

    status, _ = call("GET", "/users/list/")
    expect("list users", False, status)

    status, _ = call("POST", "/api/v1/dataset/", {"table_name": "anything", "database": 1}, csrf)
    expect("create a dataset", False, status)

    print()
    if failures:
        print(f"{failures} expectation(s) did not hold")
    else:
        print("public access is exactly what was intended")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
