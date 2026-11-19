"""A very small Superset API client, for provisioning dashboards from code.

Standard library only, on purpose: this runs with plain `python3` from the repo root, with no
virtualenv to create and no dependency to justify. It is infrastructure glue, not application code.

Why provision through the API at all, rather than clicking the UI: a dashboard that exists only
because somebody once filled in forms cannot be rebuilt after `docker compose down -v`, cannot be
reviewed in a pull request, and cannot be deployed to the server in Phase 12. Superset keeps its
dashboards in its own database; this repo keeps the instructions that produce them.

Authentication is the three-step dance Superset requires, and the same one Phase 9's guest-token
endpoint will have to do: log in for a bearer token, fetch a CSRF token, and send both (plus the
session cookie) on every write.
"""

import json
import os
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

BASE_URL = os.environ.get("SUPERSET_URL", "http://localhost:8088")


class SupersetError(RuntimeError):
    """An API call failed. Carries the response body, which is where Superset explains itself."""


class Superset:
    """Logged-in Superset session. Create one, then call get/post/put."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        # A cookie jar, because the CSRF token is only accepted alongside the session cookie that
        # was issued with it.
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self._token = ""
        self._csrf = ""

    def login(self, username: str, password: str) -> "Superset":
        answer = self._call(
            "POST",
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": True},
            authenticated=False,
        )
        self._token = answer["access_token"]
        self._csrf = self._call("GET", "/api/v1/security/csrf_token/")["result"]
        return self

    # --- verbs ---------------------------------------------------------------------------------

    def get(self, path: str) -> dict[str, Any]:
        return self._call("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", path, payload)

    def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("PUT", path, payload)

    # --- the one place that talks HTTP ----------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - fixed host
        request.add_header("Content-Type", "application/json")
        if authenticated:
            request.add_header("Authorization", f"Bearer {self._token}")
            if self._csrf:
                request.add_header("X-CSRFToken", self._csrf)
                request.add_header("Referer", self.base_url)  # Superset checks it alongside CSRF
        try:
            with self._opener.open(request, timeout=120) as response:
                body = response.read().decode()
        except urllib.error.HTTPError as error:
            detail = error.read().decode()[:600]
            raise SupersetError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
        return json.loads(body) if body else {}

    # --- small helpers the build scripts share --------------------------------------------------

    def find_id(self, endpoint: str, field: str, value: str) -> int | None:
        """The id of an object whose `field` equals `value`, or None.

        Used to make provisioning idempotent: every create is "find, else create", so a script can
        be re-run after a change without piling up duplicates named "Chart (1)".
        """
        query = json.dumps(
            {"filters": [{"col": field, "opr": "eq", "value": value}], "page_size": 100}
        )
        answer = self.get(f"/api/v1/{endpoint}/?q={urllib.parse.quote(query)}")
        for item in answer.get("result", []):
            if item.get(field) == value:
                return item["id"]
        return None

    def chart_data(self, chart_id: int) -> dict[str, Any]:
        """Run a chart's own saved query, the way a dashboard does.

        Reads the chart's stored `query_context` and POSTs it to /api/v1/chart/data - which is the
        request a browser sends when it renders that chart on a dashboard.

        Not `GET /api/v1/chart/{id}/data/`: that endpoint rejected these charts with a bare
        "400 Bad Request ... could not understand", while POSTing the very same stored context
        returned the right numbers. Chasing the GET would have meant debugging the verification
        instead of the thing being verified.
        """
        chart = self.get(f"/api/v1/chart/{chart_id}")["result"]
        context = chart.get("query_context")
        if not context:
            raise SupersetError(f"chart {chart_id} has no stored query_context")
        return self.post("/api/v1/chart/data", json.loads(context))


def from_env() -> "Superset":
    """A logged-in session using the admin credentials from the environment."""
    password = os.environ.get("SUPERSET_ADMIN_PASSWORD")
    if not password:
        raise KeyError("set SUPERSET_ADMIN_PASSWORD (see .env.example)")
    username = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    return Superset().login(username, password)
