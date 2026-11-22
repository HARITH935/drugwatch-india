"""Superset's configuration, assembled from environment variables.

Mounted into the container at /app/pythonpath/superset_config.py. Everything secret comes from the
environment (CLAUDE.md §4), so this file is safe to commit and the same file serves local dev and
production - only `.env` differs.

Superset keeps its own bookkeeping (dashboards, charts, users) in the `superset` database, beside
`drugwatch` and `airflow` in the same Postgres. It reads the warehouse as `superset_reader`, a role
with SELECT on `gold` and nothing else (infra/postgres/superset_reader.sql).
"""

import os

# --- identity ----------------------------------------------------------------------------------
# Signs session cookies and encrypts stored database passwords. No default on purpose: Superset
# ships with a well-known development key, and anyone holding it can forge a session.
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# --- Superset's own metadata database ------------------------------------------------------------
# `postgres:5432` is the in-network address; the Mac reaches the same server on localhost:5433.
_user = os.environ.get("POSTGRES_USER", "drugwatch")
_password = os.environ["POSTGRES_PASSWORD"]
SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{_user}:{_password}@postgres:5432/superset"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# --- caching ------------------------------------------------------------------------------------
# Redis is already running for the API (plan §6). Superset will not start in production mode with
# the default in-memory caches, and they would be useless here anyway: every worker would hold its
# own copy and a restart would drop the lot.
_redis = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_HOST": os.environ.get("REDIS_HOST", "redis"),
    "CACHE_REDIS_PORT": int(os.environ.get("REDIS_PORT", "6379")),
}
CACHE_CONFIG = {**_redis, "CACHE_DEFAULT_TIMEOUT": 300, "CACHE_KEY_PREFIX": "superset_"}
DATA_CACHE_CONFIG = {**_redis, "CACHE_DEFAULT_TIMEOUT": 3600, "CACHE_KEY_PREFIX": "superset_data_"}
FILTER_STATE_CACHE_CONFIG = {
    **_redis,
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_filter_",
}
EXPLORE_FORM_DATA_CACHE_CONFIG = {
    **_redis,
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_form_",
}
# The data cache holds query results for an hour. The warehouse is rebuilt monthly, so an hour of
# staleness on a public dashboard is invisible, and it keeps a shared link from re-running every
# chart's SQL for every visitor.

# --- what this Superset may do -------------------------------------------------------------------
ROW_LIMIT = 50_000  # a chart that needs more rows than this is asking the wrong question
SUPERSET_WEBSERVER_TIMEOUT = 60
SQLLAB_TIMEOUT = 60
# Embedding (EMBEDDED_SUPERSET) belongs to Phase 9's guest-token endpoint. Not enabled here: a
# feature flag switched on "ready for later" is a feature nobody has tested.
FEATURE_FLAGS: dict[str, bool] = {
    # Lets a dashboard be embedded in another site with a short-lived guest token, which is how
    # Phase 11's Next.js pages will show them. Without it, /api/v1/security/guest_token/ answers
    # 404 and the embedding SDK has nothing to present.
    "EMBEDDED_SUPERSET": True,
}

# --- embedding ------------------------------------------------------------------------------------
# The role a guest token carries. A dedicated role rather than the default "Public": embedding is a
# separate grant, and Phase 12 must be able to lock down anonymous browsing without silently
# changing what an embedded dashboard can do, or the other way round.
# infra/superset/configure_embedding.py builds it by COPYING the Public role's permissions, so the
# two stay identical in content while remaining separate decisions.
GUEST_ROLE_NAME = "EmbeddedViewer"

# Five minutes. A guest token is a bearer credential in a browser and cannot be withdrawn once
# issued, so its lifetime is the only limit on a copied one. Phase 9's endpoint hands out a fresh
# one on request, and the embedding SDK refreshes before expiry - so short costs nothing.
GUEST_TOKEN_JWT_EXP_SECONDS = 300

# Signed with its own secret, not reused from SECRET_KEY. Superset falls back to SECRET_KEY when
# this is unset, which would mean one leaked value forged both session cookies and guest tokens.
GUEST_TOKEN_JWT_SECRET = os.environ["SUPERSET_GUEST_TOKEN_SECRET"]

# --- local HTTP ----------------------------------------------------------------------------------
# Talisman sets HTTPS-only security headers (HSTS, secure cookies) and the Content Security Policy.
# On http://localhost it would make the login cookie unusable, so it is off here - and Superset
# logs a warning about the missing CSP on every start, which is left visible on purpose.
# **Phase 12 must set TALISMAN_ENABLED = True with a CSP before this is exposed to the internet.**
# The warning is not silenced (CONTENT_SECURITY_POLICY_WARNING) precisely so it keeps nagging.
TALISMAN_ENABLED = False
WTF_CSRF_ENABLED = True
# Long enough that a dashboard left open overnight does not fail its next request with a CSRF error.
WTF_CSRF_TIME_LIMIT = 60 * 60 * 24

# --- how it describes itself ---------------------------------------------------------------------
APP_NAME = "DrugWatch India"
# Shown on every page of this Superset instance (CLAUDE.md §6). The dashboards carry their own
# disclaimer too (step 5); this is the backstop for any view that somehow does not.
FAB_ADD_SECURITY_VIEWS = True
