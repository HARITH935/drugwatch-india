# Superset, plus the one thing its official image deliberately leaves out: a database driver.
#
# apache/superset:6.1.0 ships no Postgres driver at all - not psycopg2, psycopg, pg8000 or asyncpg
# (checked, not assumed). The image is deliberately slim: Superset can talk to thirty-odd database
# engines and bundling every driver would make it enormous, so each deployment installs the ones it
# actually uses. Without this, `superset db upgrade` fails with ModuleNotFoundError: psycopg2,
# because Superset's own metadata lives in Postgres here too.
#
# Two details that are easy to get wrong:
#
#   - **The venv.** `python` in this image is /app/.venv/bin/python, but `pip` on PATH is
#     /usr/local/bin/pip - the system one. `pip install psycopg2-binary` would appear to succeed and
#     install into a Python that Superset never runs. The install is therefore aimed explicitly at
#     the venv's interpreter.
#   - **The user.** The image runs as `superset` (uid 1000), which cannot write into /app/.venv.
#     Root installs the driver; the final USER puts it back, because a web service exposed to the
#     internet (Phase 12) should not run as root.
#
# `uv` is already in the image, and is what the rest of this repo uses (ADR 0005).

FROM apache/superset:6.1.0

USER root

# psycopg2-binary rather than psycopg2: no build toolchain needed in the image, and it is the same
# driver version the orchestration project resolved for Airflow.
RUN uv pip install --python /app/.venv/bin/python --no-cache psycopg2-binary==2.9.13

USER superset
