#!/usr/bin/env bash
# Repo hygiene checks. CI runs this (.github/workflows/lint.yml); you can run it locally too:
#   bash .github/scripts/repo-checks.sh
# Exit code 0 = all checks passed; 1 = at least one failed (turns the CI run red).
set -euo pipefail # stop on any error, on unset variables, and on failures inside pipes

cd "$(git rev-parse --show-toplevel)" # always run from the repo root
fail=0

echo "== 1. No .env files committed (only .env.example is allowed) =="
# git ls-files = every file git tracks (committed or staged)
leaked=$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v -E '(^|/)\.env\.example$' || true)
if [ -n "$leaked" ]; then
  echo "FAIL: these env files are tracked by git and may contain secrets:"
  echo "$leaked"
  fail=1
else
  echo "ok"
fi

echo "== 2. Every \${VAR} used in docker-compose.yml is listed in .env.example =="
# Skip comment lines/trailing comments so example text like \${VAR} in comments isn't counted
vars=$(grep -v '^[[:space:]]*#' docker-compose.yml | sed 's/ #.*//' | grep -o '\${[A-Z_][A-Z0-9_]*' | tr -d '${' | sort -u)
for v in $vars; do
  if grep -q "^$v=" .env.example; then
    echo "ok       $v"
  else
    echo "MISSING  $v (add it to .env.example)"
    fail=1
  fi
done

echo "== 3. docker-compose.yml is valid when filled from .env.example =="
# Fill each blank value in the template with a dummy, then ask Compose to parse everything.
tmp_env=$(mktemp)
sed -E 's/^([A-Z_][A-Z0-9_]*)=$/\1=ci-dummy-value/' .env.example >"$tmp_env"
if docker compose --env-file "$tmp_env" config --quiet; then
  echo "ok"
else
  echo "FAIL: docker compose could not parse docker-compose.yml"
  fail=1
fi
rm -f "$tmp_env"

exit "$fail"
