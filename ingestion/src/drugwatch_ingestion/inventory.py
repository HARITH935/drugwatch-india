"""Inventory check for raw/: is everything there, complete and unchanged? (Phase 1 step 5e)

Lists the whole bucket and checks that:
1. every file has its .meta.json sidecar, and every sidecar has its file;
2. each sidecar has the required fields, and its "key" is the file it sits next to;
3. each file's bytes still hash to the SHA-256 in its name and in its sidecar (nothing edited or
   corrupted: raw/ is never modified, CLAUDE.md §5).

Prints counts per source and dataset, and exits with status 1 if any check fails, so a scheduler
(Airflow, Phase 5) can stop on it. Reads only from RustFS: no website requests.

Run (from ingestion/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_ingestion.inventory
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from drugwatch_ingestion.store import META_SUFFIX, RawStore

SIDECAR_FIELDS = ("source", "method", "key", "sha256", "size_bytes", "stored_at")
_HASH_NAME = re.compile(r"[0-9a-f]{64}")  # a data file is named <sha256>.<ext>


@dataclass
class Group:
    """Totals for one (source, dataset), e.g. ("nppa", "orders")."""

    files: int = 0
    manual: int = 0  # files that came from a browser download (method = "manual")
    size_bytes: int = 0


@dataclass
class Report:
    groups: dict[tuple[str, str], Group] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def files(self) -> int:
        return sum(group.files for group in self.groups.values())


def check_bucket(s3: Any, bucket: str = "raw", *, verify_hashes: bool = True) -> Report:
    """Check every file and sidecar in the bucket. verify_hashes=False skips reading the files
    (much faster, but can't catch changed bytes)."""
    keys = set(_all_keys(s3, bucket))
    sidecars = {key for key in keys if key.endswith(META_SUFFIX)}
    files = keys - sidecars
    report = Report()

    for key in sorted(files - {sidecar.removesuffix(META_SUFFIX) for sidecar in sidecars}):
        report.problems.append(f"{key}: no sidecar (an interrupted write? rerun its download)")

    for sidecar_key in sorted(sidecars):
        key = sidecar_key.removesuffix(META_SUFFIX)
        if key not in files:
            report.problems.append(f"{sidecar_key}: its file {key} is missing")
            continue
        meta = _read_sidecar(s3, bucket, sidecar_key, report)
        if meta is None:
            continue
        problems = _check_file(s3, bucket, key, meta, verify_hashes)
        report.problems += [f"{key}: {problem}" for problem in problems]
        group = report.groups.setdefault((meta["source"], meta.get("dataset") or "-"), Group())
        group.files += 1
        group.manual += meta["method"] == "manual"
        group.size_bytes += meta["size_bytes"]
    return report


def _all_keys(s3: Any, bucket: str) -> Iterator[str]:
    """Every key in the bucket. A listing returns at most 1,000 keys, so follow the pages."""
    token = None
    while True:
        page = s3.list_objects_v2(Bucket=bucket, **({"ContinuationToken": token} if token else {}))
        yield from (obj["Key"] for obj in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return
        token = page["NextContinuationToken"]


def _read_sidecar(s3: Any, bucket: str, sidecar_key: str, report: Report) -> dict | None:
    try:
        meta = json.loads(s3.get_object(Bucket=bucket, Key=sidecar_key)["Body"].read())
    except ValueError:
        report.problems.append(f"{sidecar_key}: not valid JSON")
        return None
    missing = [name for name in SIDECAR_FIELDS if name not in meta]
    if missing:
        report.problems.append(f"{sidecar_key}: missing fields {missing}")
        return None
    return meta


def _check_file(s3: Any, bucket: str, key: str, meta: dict, verify_hashes: bool) -> list[str]:
    problems = []
    name_hash = key.rsplit("/", 1)[-1].split(".", 1)[0]
    if meta["key"] != key:
        problems.append(f"sidecar says it belongs to {meta['key']}")
    if not _HASH_NAME.fullmatch(name_hash) or name_hash != meta["sha256"]:
        problems.append(f"file name hash {name_hash[:12]}… doesn't match sidecar sha256")
    if verify_hashes:
        digest, size = hashlib.sha256(), 0
        for chunk in s3.get_object(Bucket=bucket, Key=key)["Body"].iter_chunks(1024 * 1024):
            digest.update(chunk)  # hash in 1 MB chunks: big files never sit in memory whole
            size += len(chunk)
        if digest.hexdigest() != meta["sha256"]:
            problems.append("bytes no longer match their SHA-256 (changed or corrupted)")
        if size != meta["size_bytes"]:
            problems.append(f"size is {size} bytes, sidecar says {meta['size_bytes']}")
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check that raw/ is complete and unchanged.")
    parser.add_argument("--bucket", default="raw")
    parser.add_argument("--no-hash", action="store_true", help="skip re-hashing files (faster)")
    args = parser.parse_args(argv)

    report = check_bucket(RawStore.from_env().s3, args.bucket, verify_hashes=not args.no_hash)
    print(f"{'source':<14} {'dataset':<16} {'files':>6} {'manual':>7} {'MB':>8}")
    for (source, dataset), group in sorted(report.groups.items()):
        size_mb = group.size_bytes / 1e6
        print(f"{source:<14} {dataset:<16} {group.files:>6} {group.manual:>7} {size_mb:>8.1f}")
    total_mb = sum(group.size_bytes for group in report.groups.values()) / 1e6
    checked = "names, sidecars and SHA-256 of every file" if not args.no_hash else "names, sidecars"
    print(f"{'total':<31} {report.files:>6} {'':>7} {total_mb:>8.1f}   (checked: {checked})")
    if report.problems:
        print(f"\n{len(report.problems)} PROBLEM(S):")
        for problem in report.problems:
            print(f"  - {problem}")
        sys.exit(1)  # non-zero exit status: a scheduler treats the run as failed
    print("no problems found")


if __name__ == "__main__":
    main()
