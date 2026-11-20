#!/usr/bin/env bash
# Recreate the dashboards in a Superset from the YAML in this repo.
#
# This is the deployment path Phase 12 will use, tested here rather than discovered on a server:
# `infra/superset/assets/` holds the exported bundle, and this script rebuilds the zip Superset's
# importer expects and feeds it in.
#
# **The wrapper directory matters.** Superset's exporter writes everything under a timestamped top
# folder; export_assets.py strips it so the repo gets clean diffs instead of a new directory per
# export. The importer, though, requires that folder - without it the import dies in the middle of
# a JSON decode with no useful message. So it is added back here.
#
# The database password is not in the bundle (the exporter masks it as XXXXXXXXXX), so the
# connection keeps whatever password the target Superset already has for it. On a fresh Superset,
# run register_gold_database.sh first.
#
# Run from the repo root, with the stack up:
#   bash infra/superset/import_assets.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

assets="infra/superset/assets"
[ -d "$assets" ] || { echo "no $assets - run export_assets.py first" >&2; exit 1; }

staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

mkdir -p "$staging/dashboard_export"
cp -R "$assets/." "$staging/dashboard_export/"
(cd "$staging" && zip -qr bundle.zip dashboard_export)

docker compose cp "$staging/bundle.zip" superset:/tmp/drugwatch_assets.zip >/dev/null
docker compose exec -T superset superset import-dashboards \
  -p /tmp/drugwatch_assets.zip -u "${SUPERSET_ADMIN_USERNAME:-admin}" 2>&1 |
  grep -viE "INFO|WARNING|fastmcp|Loaded your|warnings.warn" || true

echo "imported $(find "$assets" -name '*.yaml' | wc -l | tr -d ' ') asset file(s)"
echo "verify with: set -a && . ./.env && set +a && python3 infra/superset/verify_charts.py"
