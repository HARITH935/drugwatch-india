#!/usr/bin/env bash
# Register (or re-point) Superset's connection to the gold layer.
#
# Scripted rather than clicked through the UI, for the same reason the dashboards are exported as
# code in step 5: a connection that exists only because somebody once filled in a form cannot be
# rebuilt after `docker compose down -v`, and cannot be reviewed.
#
# Superset connects as `superset_reader`, which has SELECT on `gold` and nothing else
# (infra/postgres/superset_reader.sql). The password is read from .env and handed to the container
# for this one command: the running service never holds it in its environment, because Superset
# stores the connection encrypted in its own metadata database once it is created.
#
# Idempotent: `set-database-uri` creates the connection when missing and updates it otherwise.
#
# Run from the repo root, with the stack up:
#   bash infra/superset/register_gold_database.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

if [ ! -f .env ]; then
  echo "no .env in $(pwd) - copy .env.example and fill it in" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a && . ./.env && set +a

: "${SUPERSET_READER_PASSWORD:?set SUPERSET_READER_PASSWORD in .env (see .env.example)}"

DATABASE_NAME="DrugWatch gold"

# `postgres:5432` is the in-network address: Superset talks to the database container directly,
# not through the port published to the Mac.
# The URI is single-quoted so THIS shell leaves ${READER_PASSWORD} alone and the container's shell
# expands it. Building the URI here instead would put the password in the host's argv, where it is
# visible to `ps` for as long as the command runs.
docker compose exec -T -e READER_PASSWORD="$SUPERSET_READER_PASSWORD" superset bash -c '
  superset set-database-uri \
    --database_name "'"$DATABASE_NAME"'" \
    --uri "postgresql+psycopg2://superset_reader:${READER_PASSWORD}@postgres:5432/drugwatch"
'

echo "registered '$DATABASE_NAME' (reads the gold schema only)"
