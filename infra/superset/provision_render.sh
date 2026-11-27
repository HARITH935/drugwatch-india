#!/usr/bin/env bash
# Provision the PRODUCTION Superset (Phase 12 step 3, ADR 0021): register gold, import the
# dashboards, and build the public and embedding roles.
#
# Why this script exists at all. The four scripts it wraps - register_gold_database.sh,
# import_assets.sh, configure_public_role.py, configure_embedding.py - all reach their Superset
# through `docker compose exec`, because each needs either Superset's CLI or its Flask app context,
# neither of which the REST API exposes. Render's free instances have **no shell access**, so none
# of them can run against the deployed service.
#
# They do not actually need *that* Superset, though: Superset keeps all of this state - database
# connections, datasets, charts, dashboards, roles, permissions - in its metadata database and
# nowhere else. So this runs the same production image **locally**, pointed at the same Neon
# metadata database the Render service reads, and drives the existing scripts through it. The
# Render service picks the result up on its next request. Nothing is rewritten, nothing is clicked.
#
# Two things matter here, and both were learned the hard way:
#
#   1. **The staged bundle gets the real connection URI written into it before import.** The
#      committed bundle carries `postgresql+psycopg2://superset_reader:XXXXXXXXXX@postgres:5432/
#      drugwatch` - local host, masked password - and Superset 6.1's importer rejects that mask
#      outright (`{'_schema': ['Must provide a password for the database']}`), **even when the
#      connection already exists**, which is what `import_assets.sh`'s comment assumes. Importing
#      afterwards would also have overwritten the Neon URI with a hostname Render cannot resolve.
#      Rewriting the staged copy settles both; the committed file is never touched, so the repo
#      keeps no password and no production host.
#   2. **`--network drugwatch_default`, not Docker's default bridge.** On the default bridge, DNS
#      in this VM could not resolve Neon's hostname at all, and psycopg2 waited on it silently -
#      two `superset init` runs hung for over half an hour each with no error (see PROGRESS.md).
#
# The gold connection uses Neon's **pooled** endpoint: Superset issues many short analytical reads,
# which is exactly what a transaction pooler is for. Its own metadata connection uses the direct
# endpoint instead, because that one runs migrations (DDL).
#
# Idempotent: every step it calls is. Safe to re-run after changing a dashboard or a role.
#
# Run from the repo root:
#   set -a && . ./.env && set +a && bash infra/superset/provision_render.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

[ -f .env ] || { echo "no .env in $(pwd)" >&2; exit 1; }
# shellcheck disable=SC1091
set -a && . ./.env && set +a

: "${NEON_DATABASE_URL:?set NEON_DATABASE_URL in .env}"
: "${NEON_SUPERSET_READER_PASSWORD:?set NEON_SUPERSET_READER_PASSWORD in .env}"
: "${SUPERSET_DATABASE_URL:?set SUPERSET_DATABASE_URL in .env}"
: "${RENDER_SUPERSET_SECRET_KEY:?set RENDER_SUPERSET_SECRET_KEY in .env}"
: "${RENDER_SUPERSET_GUEST_TOKEN_SECRET:?set RENDER_SUPERSET_GUEST_TOKEN_SECRET in .env}"
: "${RENDER_SUPERSET_EMBED_PASSWORD:?set RENDER_SUPERSET_EMBED_PASSWORD in .env}"

IMAGE=drugwatch/superset:render
CONTAINER=superset-provision
DATABASE_NAME="DrugWatch gold"
ASSETS=infra/superset/assets

[ -d "$ASSETS" ] || { echo "no $ASSETS - run export_assets.py first" >&2; exit 1; }

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "==> starting a local $IMAGE against the production metadata database"
# `sleep infinity` instead of the image's gunicorn: this container is a wrench, not a server.
docker run -d --name "$CONTAINER" --network drugwatch_default \
  -e SUPERSET_SECRET_KEY="$RENDER_SUPERSET_SECRET_KEY" \
  -e SUPERSET_GUEST_TOKEN_SECRET="$RENDER_SUPERSET_GUEST_TOKEN_SECRET" \
  -e SUPERSET_DATABASE_URL="$SUPERSET_DATABASE_URL" \
  -e UPSTASH_REDIS_URL="${UPSTASH_REDIS_URL:-}" \
  -e SUPERSET_EMBED_USERNAME="${SUPERSET_EMBED_USERNAME:-embed_service}" \
  -e SUPERSET_EMBED_PASSWORD="$RENDER_SUPERSET_EMBED_PASSWORD" \
  --entrypoint sleep "$IMAGE" infinity >/dev/null

# The password is handed over as an environment variable and the URI is assembled by the
# container's shell, so it never appears in this host's argv where `ps` could read it.
GOLD_HOST_AND_DB=$(printf '%s' "$NEON_DATABASE_URL" | sed -E 's#^postgresql://[^@]*@##')

register_gold() {
  local log="${1:-/dev/stderr}"
  if ! docker exec -e READER_PASSWORD="$NEON_SUPERSET_READER_PASSWORD" \
       -e GOLD_HOST_AND_DB="$GOLD_HOST_AND_DB" "$CONTAINER" bash -c '
         superset set-database-uri \
           --database_name "'"$DATABASE_NAME"'" \
           --uri "postgresql+psycopg2://superset_reader:${READER_PASSWORD}@${GOLD_HOST_AND_DB}"
       ' > "$log" 2>&1; then
    echo "set-database-uri FAILED:" >&2
    grep -iE "error|Traceback|invalid|refus" "$log" | head -15 >&2
    return 1
  fi
}

echo "==> importing $(find "$ASSETS" -name '*.yaml' | wc -l | tr -d ' ') asset file(s)"
staging=$(mktemp -d)
chmod 700 "$staging"
trap 'rm -rf "$staging"; cleanup' EXIT
# The wrapper directory is required by Superset's importer, and export_assets.py strips it so the
# repo gets clean diffs - so it is added back here, exactly as import_assets.sh does.
mkdir -p "$staging/dashboard_export"
cp -R "$ASSETS/." "$staging/dashboard_export/"

# Rewrite the staged copy's connection URI - never the committed one, which keeps its masked
# password and local host so the repo stays safe to publish.
#
# This replaces what used to be a register / import / register-again dance. Superset 6.1's
# importer validates the bundle's schema and rejects `XXXXXXXXXX` outright
# (`{'_schema': ['Must provide a password for the database']}`) **even when the connection already
# exists** - so registering first does not help, and registering afterwards is then needed only to
# undo the local hostname the bundle would have written. Giving the bundle the real URI up front
# settles both at once. Values arrive by environment, not argv, and the staging directory is 0700
# and deleted on exit.
GOLD_URI="postgresql+psycopg2://superset_reader:${NEON_SUPERSET_READER_PASSWORD}@${GOLD_HOST_AND_DB}" \
  python3 - "$staging/dashboard_export/databases/DrugWatch_gold.yaml" <<'PY'
import os, re, sys
path = sys.argv[1]
with open(path) as fh:
    text = fh.read()
new, count = re.subn(r"(?m)^sqlalchemy_uri:.*$", "sqlalchemy_uri: " + os.environ["GOLD_URI"], text)
if count != 1:
    sys.exit(f"expected exactly one sqlalchemy_uri line in {path}, found {count}")
with open(path, "w") as fh:
    fh.write(new)
PY

(cd "$staging" && zip -qr bundle.zip dashboard_export)
docker cp "$staging/bundle.zip" "$CONTAINER:/tmp/assets.zip" >/dev/null
# Not filtered into silence: an import that fails validation says exactly why, and the first
# version of this script threw that away behind a `grep -v ... || true`, reporting success while
# importing nothing at all.
#
# Retried, because Neon drops a connection mid-operation often enough to matter (`SSL SYSCALL
# error: EOF detected` - a compute that scales to zero). The import runs with overwrite=True, so
# repeating it is safe and picks up where the last attempt left off.
imported=0
for attempt in 1 2 3 4; do
  if docker exec "$CONTAINER" \
       superset import-dashboards -p /tmp/assets.zip -u "${SUPERSET_ADMIN_USERNAME:-admin}" \
       > "$staging/import.log" 2>&1; then
    imported=1
    break
  fi
  echo "    attempt $attempt failed: $(grep -ioE "SSL SYSCALL error: EOF detected|Must provide a password[^']*|CommandInvalidError[^\"]*" "$staging/import.log" | head -1)"
  sleep 5
done
if [ "$imported" -ne 1 ]; then
  echo "import FAILED after 4 attempts:" >&2
  grep -iE "error|_schema|Traceback|CommandInvalid" "$staging/import.log" | head -20 >&2
  exit 1
fi

# A safety net, not the main mechanism: the bundle above already carries the Neon URI. This
# re-asserts it, so a future export that somehow reintroduced the local host would not silently
# leave production pointing at a hostname Render cannot resolve.
echo "==> re-asserting '$DATABASE_NAME' -> Neon"
register_gold /tmp/drugwatch-register.log

echo "==> configuring the anonymous (Public) role"
docker exec -i "$CONTAINER" python - < infra/superset/configure_public_role.py

echo "==> configuring embedding (EmbeddedViewer role + the guest-token service account)"
docker exec -i "$CONTAINER" python - < infra/superset/configure_embedding.py

echo "==> checking what actually landed in the production metadata"
# Read straight from the metadata database rather than trusting the steps above: the first run of
# this script printed four happy sections and had imported nothing.
NEON_HOST=$(printf '%s' "$GOLD_HOST_AND_DB" | sed -E 's#[:/?].*##')
summary=$(docker compose exec -T postgres psql "$SUPERSET_DATABASE_URL" -tAc "
  select (select count(*) from dashboards) || ' dashboards, '
      || (select count(*) from slices)     || ' charts, '
      || (select count(*) from tables)     || ' datasets'")
gold_uri=$(docker compose exec -T postgres psql "$SUPERSET_DATABASE_URL" -tAc \
  "select sqlalchemy_uri from dbs where database_name = '$DATABASE_NAME'")
echo "    $summary"
echo "    '$DATABASE_NAME' -> $gold_uri"

failed=0
case "$summary" in 0\ dashboards*) echo "    ^ no dashboards were imported" >&2; failed=1 ;; esac
case "$gold_uri" in
  *"$NEON_HOST"*) ;;
  *) echo "    ^ the gold connection does not point at Neon ($NEON_HOST)" >&2; failed=1 ;;
esac
[ "$failed" -eq 0 ] || { echo "refusing to report success" >&2; exit 1; }

echo
echo "done. Verify against the live service, not this container:"
echo "  SUPERSET_URL=<render url> python3 infra/superset/verify_charts.py"
echo "  SUPERSET_URL=<render url> python3 infra/superset/public_access_test.py"
