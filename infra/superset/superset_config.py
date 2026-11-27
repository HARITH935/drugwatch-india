"""Superset's configuration, assembled from environment variables.

Mounted into the container at /app/pythonpath/superset_config.py. Everything secret comes from the
environment (CLAUDE.md §4), so this file is safe to commit and the same file serves local dev and
production - only `.env` differs.

Superset keeps its own bookkeeping (dashboards, charts, users) in the `superset` database, beside
`drugwatch` and `airflow` in the same Postgres. It reads the warehouse as `superset_reader`, a role
with SELECT on `gold` and nothing else (infra/postgres/superset_reader.sql).
"""

import os

# Phase 12 (ADR 0021's amendment): true once this is deployed to Render, false on every local
# docker-compose run (nothing sets it there). Everything below that differs between local dev and
# production reads this one flag, rather than each setting guessing from its own env var - one
# place to see what changes when this goes from a laptop to the public internet.
#
# NOT the built-in SUPERSET_ENV: the official apache/superset image already sets that to
# "production" by default (confirmed by inspecting the running local container, not assumed), so
# reusing that name turned Talisman's force_https on for local dev too, which breaks the plain-HTTP
# login page with a redirect loop - caught immediately by testing right after this was written.
IS_PRODUCTION = os.environ.get("SUPERSET_DEPLOY_ENV") == "production"

# --- identity ----------------------------------------------------------------------------------
# Signs session cookies and encrypts stored database passwords. No default on purpose: Superset
# ships with a well-known development key, and anyone holding it can forge a session.
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# --- Superset's own metadata database ------------------------------------------------------------
# Locally this is `postgres:5432/superset`, the in-network address (the Mac reaches the same
# server on localhost:5433). Production has no such network - its metadata lives in its own
# database on Neon instead, given here as one full connection string rather than host/port, since
# that is the form Neon hands out.
_metadata_url = os.environ.get("SUPERSET_DATABASE_URL")
if _metadata_url:
    # Neon gives a plain `postgresql://` URL; SQLAlchemy needs the driver named in the scheme.
    SQLALCHEMY_DATABASE_URI = _metadata_url.replace("postgresql://", "postgresql+psycopg2://", 1)
else:
    _user = os.environ.get("POSTGRES_USER", "drugwatch")
    _password = os.environ["POSTGRES_PASSWORD"]
    SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{_user}:{_password}@postgres:5432/superset"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Keep the metadata connection honest. A managed Postgres that scales to zero (Neon's free plan
# does) will close a connection that has gone quiet, and `superset init` has stretches where it
# builds its permission list in Python between queries - long enough to be dropped mid-run.
#
# When that close arrives cleanly, psycopg2 raises "SSL SYSCALL error: EOF detected". When it does
# not, the client sits in a socket read **forever**, because Linux waits two hours before probing
# a silent connection. Both were observed here: one run died with that error, another hung at 0%
# CPU with no error at all, having written 90 of its permission rows.
#
# So: ask the kernel to probe after 30s of quiet and give up inside a minute, hand out no pooled
# connection without checking it first, and retire connections before any upstream idle timeout
# can. Set for local dev too - a laptop that sleeps drops connections the same way.
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
    "connect_args": {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
}

# --- caching ------------------------------------------------------------------------------------
# Redis is already running for the API (plan §6). Superset will not start in production mode with
# the default in-memory caches, and they would be useless here anyway: every worker would hold its
# own copy and a restart would drop the lot.
# Production's Redis is Upstash, which needs TLS and a password - given as one `rediss://` URL,
# the one thing flask-caching's RedisCache accepts in place of separate host/port settings. Shared
# with the backend's rate limiter (CLAUDE.md §10): different key prefixes below keep them apart.
_upstash_url = os.environ.get("UPSTASH_REDIS_URL")
if _upstash_url:
    _redis = {"CACHE_TYPE": "RedisCache", "CACHE_REDIS_URL": _upstash_url}
else:
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

# --- local HTTP vs production HTTPS ---------------------------------------------------------------
# Talisman sets HTTPS-only security headers (HSTS, secure cookies) and the Content Security Policy
# - a browser-enforced allowlist of where scripts, styles and frames are allowed to load from. On
# http://localhost it would make the login cookie unusable, so it stays off there - and Superset
# logs a warning about the missing CSP on every start, left visible on purpose
# (CONTENT_SECURITY_POLICY_WARNING is not silenced).
TALISMAN_ENABLED = IS_PRODUCTION
if IS_PRODUCTION:
    # Render terminates HTTPS at its edge and talks to this container over plain HTTP, so without
    # ProxyFix, Talisman would see every request as insecure and redirect-loop trying to "upgrade"
    # a connection that is already secure. 1 proxy layer: Render sits in front exactly once.
    ENABLE_PROXY_FIX = True
    PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 1, "x_port": 1, "x_prefix": 1}
    # 'unsafe-inline'/'unsafe-eval': Superset's own open-source frontend bundle relies on both and
    # ships no nonce to allow them more narrowly - the same allowance Superset's own docs show.
    # frame-ancestors is what actually matters for embedding (step 5): it names the one site
    # allowed to put this in an iframe, read from SITE_URL since that already means "the public
    # frontend" everywhere else in this repo (CLAUDE.md §10).
    TALISMAN_CONFIG = {
        "force_https": True,
        "session_cookie_secure": True,
        "content_security_policy": {
            "default-src": "'self'",
            "img-src": ["'self'", "data:", "blob:"],
            "style-src": ["'self'", "'unsafe-inline'"],
            "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
            "font-src": ["'self'", "data:"],
            "connect-src": "'self'",
            "object-src": "'none'",
            "frame-ancestors": ["'self'", os.environ.get("SITE_URL", "http://localhost:3100")],
        },
    }
WTF_CSRF_ENABLED = True
# Long enough that a dashboard left open overnight does not fail its next request with a CSRF error.
WTF_CSRF_TIME_LIMIT = 60 * 60 * 24

# --- how it describes itself ---------------------------------------------------------------------
APP_NAME = "DrugWatch India"
# Shown on every page of this Superset instance (CLAUDE.md §6). The dashboards carry their own
# disclaimer too (step 5); this is the backstop for any view that somehow does not.
FAB_ADD_SECURITY_VIEWS = True
