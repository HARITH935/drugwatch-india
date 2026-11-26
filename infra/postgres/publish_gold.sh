#!/usr/bin/env bash
# Phase 12 step 1: copy the `gold` schema from this Mac's Postgres to Neon (production), in one
# transaction.
#
# Runs pg_dump and pg_restore INSIDE the local postgres container, not on this Mac: the Mac has
# no Postgres client tools installed, and the container already has the exact matching version
# (17.11) with outbound internet access. The dump is piped straight into pg_restore inside that
# same container - never written to this Mac - so the one new thing on disk is the dump happening
# entirely on the far side of `docker compose exec`.
#
# --single-transaction wraps the whole restore (DDL and every row) in one COMMIT, the same
# "readers never see a half-replaced table" guarantee load_silver.py already gives staging.
# --clean --if-exists drops the previous gold objects first, inside that same transaction, so a
# second run (next month's refreshed gold) replaces rather than piles on top.
#
# Run from the repo root, with the local stack up and gold built (dbt build):
#   set -a && . ./.env && set +a && bash infra/postgres/publish_gold.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

if [ ! -f .env ]; then
  echo "no .env in $(pwd) - copy .env.example and fill it in" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a && . ./.env && set +a

: "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}"
: "${NEON_DATABASE_URL:?set NEON_DATABASE_URL in .env - the connection string Neon gave you}"

echo "dumping gold from the local database..."
docker compose exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_dump -h localhost -U "${POSTGRES_USER:-drugwatch}" -d "${POSTGRES_DB:-drugwatch}" \
    --schema=gold --format=custom --no-owner --no-privileges \
  > /tmp/drugwatch-gold.dump

echo "restoring into Neon..."
docker compose cp /tmp/drugwatch-gold.dump postgres:/tmp/drugwatch-gold.dump
docker compose exec -T postgres \
  pg_restore --dbname="$NEON_DATABASE_URL" \
    --single-transaction --clean --if-exists --no-owner --no-privileges \
    /tmp/drugwatch-gold.dump
docker compose exec -T postgres rm -f /tmp/drugwatch-gold.dump
rm -f /tmp/drugwatch-gold.dump

echo "row counts (local vs Neon), every gold table - not a hand-picked sample:"
tables=$(docker compose exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -h localhost -U "${POSTGRES_USER:-drugwatch}" -d "${POSTGRES_DB:-drugwatch}" \
  -tAc "select tablename from pg_tables where schemaname = 'gold' order by tablename")

mismatch=0
for table in $tables; do
  local_count=$(docker compose exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
    psql -h localhost -U "${POSTGRES_USER:-drugwatch}" -d "${POSTGRES_DB:-drugwatch}" \
    -tAc "select count(*) from gold.${table}")
  neon_count=$(docker compose exec -T postgres \
    psql "$NEON_DATABASE_URL" -tAc "select count(*) from gold.${table}")
  printf '  %-30s local=%-8s neon=%s\n' "$table" "$local_count" "$neon_count"
  if [ "$local_count" != "$neon_count" ]; then
    echo "  ^ mismatch on $table" >&2
    mismatch=1
  fi
done

if [ "$mismatch" -ne 0 ]; then
  echo "refusing to call this a success - at least one table's row count did not match" >&2
  exit 1
fi

echo "done: gold published to Neon, every table's row count matches."
