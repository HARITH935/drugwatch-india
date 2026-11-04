#!/bin/sh
# Create the data-lake buckets in RustFS if they don't exist yet.
# Idempotent: safe to run any number of times; existing buckets are left untouched.
# Runs automatically as the one-shot `rustfs-init` service in docker-compose.yml.
#
# Needs these environment variables:
#   S3_ENDPOINT        e.g. http://rustfs:9000 (inside Docker) or http://localhost:9000 (from your Mac)
#   RUSTFS_ACCESS_KEY  RUSTFS_SECRET_KEY
#   BUCKETS            space-separated list, e.g. "raw bronze silver"
#
# Uses curl's built-in AWS Signature V4 signing, so no extra S3 tool is needed.
set -eu

: "${S3_ENDPOINT:?}" "${RUSTFS_ACCESS_KEY:?}" "${RUSTFS_SECRET_KEY:?}" "${BUCKETS:?}" # fail fast if any is unset

SIGV4="aws:amz:us-east-1:s3" # provider:service-type:region:service, the values curl signs the request with
AUTH="${RUSTFS_ACCESS_KEY}:${RUSTFS_SECRET_KEY}"

for bucket in ${BUCKETS}; do
  # HEAD = "does this bucket exist?" without downloading anything. 200 = yes, 404 = no.
  code=$(curl -s -o /dev/null -w '%{http_code}' -I --aws-sigv4 "${SIGV4}" --user "${AUTH}" "${S3_ENDPOINT}/${bucket}")
  case "${code}" in
  200)
    echo "exists   ${bucket}"
    ;;
  404)
    # PUT on a bucket path = create the bucket. -f makes curl fail on an HTTP error.
    curl -sf -o /dev/null -X PUT --aws-sigv4 "${SIGV4}" --user "${AUTH}" "${S3_ENDPOINT}/${bucket}" ||
      { echo "ERROR    ${bucket}: create failed" >&2; exit 1; }
    echo "created  ${bucket}"
    ;;
  *)
    echo "ERROR    ${bucket}: unexpected HTTP ${code} (wrong keys? RustFS down?)" >&2
    exit 1
    ;;
  esac
done
