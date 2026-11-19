#!/usr/bin/env bash
# Prove, through Superset itself, that it can read the gold layer and nothing else.
#
# The guarantee is a Postgres grant (infra/postgres/superset_reader.sql), but a grant that is only
# ever checked with psql proves nothing about the application: Superset could have been pointed at
# the wrong role, or at the `drugwatch` superuser, and every dashboard would still work - while
# quietly exposing the operational run log and pre-quality-gate silver.
#
# So this asks Superset to run the queries, over its own API, and expects two of them to fail.
#
# Run from the repo root, with the stack up:
#   bash infra/superset/smoke_test.sh

set -euo pipefail

cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
set -a && . ./.env && set +a
: "${SUPERSET_ADMIN_PASSWORD:?set SUPERSET_ADMIN_PASSWORD in .env}"

BASE_URL="http://localhost:8088"
USERNAME="${SUPERSET_ADMIN_USERNAME:-admin}"
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT

token=$(curl -sf -c "$jar" -X POST "$BASE_URL/api/v1/security/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$SUPERSET_ADMIN_PASSWORD\",\"provider\":\"db\"}" |
  python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# CSRF protection is on (superset_config.py), so a POST needs both the token and the session
# cookie. Phase 9's guest-token endpoint will have to do exactly this dance.
csrf=$(curl -sf -b "$jar" -c "$jar" -H "Authorization: Bearer $token" \
  "$BASE_URL/api/v1/security/csrf_token/" |
  python3 -c "import sys, json; print(json.load(sys.stdin)['result'])")

database_id=$(curl -sf -b "$jar" -H "Authorization: Bearer $token" "$BASE_URL/api/v1/database/" |
  python3 -c "
import sys, json
for db in json.load(sys.stdin)['result']:
    if db['database_name'] == 'DrugWatch gold':
        print(db['id']); break
else:
    raise SystemExit(\"no 'DrugWatch gold' connection - run register_gold_database.sh\")
")

run_query() {
  # No `-f` here, unlike the calls above: a refused query comes back as HTTP 4xx with the reason in
  # the body, and `--fail` would throw that body away - which is the very thing being asserted.
  curl -s -b "$jar" -X POST "$BASE_URL/api/v1/sqllab/execute/" \
    -H "Authorization: Bearer $token" -H "X-CSRFToken: $csrf" \
    -H "Content-Type: application/json" \
    -d "{\"database_id\":$database_id,\"sql\":\"$1\",\"schema\":\"gold\",\"runAsync\":false}" |
    python3 -c "
import sys, json
answer = json.load(sys.stdin)
if answer.get('data') is not None:
    print('ALLOWED', answer['data'])
else:
    print('REFUSED', (answer.get('errors') or [{}])[0].get('message', '')[:60])
"
}

failures=0
expect() { # expect <ALLOWED|REFUSED> <sql> <description>
  result=$(run_query "$2")
  if [[ "$result" == "$1"* ]]; then
    printf 'ok       %-44s %s\n' "$3" "${result:0:46}"
  else
    printf 'FAIL     %-44s %s\n' "$3" "${result:0:46}"
    failures=1
  fi
}

echo "== Superset reads gold, and only gold =="
expect ALLOWED "select count(*) as findings from gold.fact_nsq_sample" "gold.fact_nsq_sample is readable"
expect ALLOWED "select count(*) as makers from gold.dim_manufacturer" "gold.dim_manufacturer is readable"
expect REFUSED "select count(*) from staging.silver_nsq" "staging (pre-quality-gate) is refused"
expect REFUSED "select count(*) from ops.pipeline_run" "ops (run log) is refused"
expect REFUSED "select count(*) from dbt_staging.stg_nsq_sample" "dbt internals are refused"
expect REFUSED "create table gold.should_not_exist (x int)" "writing to gold is refused"

exit "$failures"
