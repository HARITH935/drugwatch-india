"""The labelled eval set (Phase 2 step 7): which rows, which split, and the labels made by hand.

SAMPLE: up to PER_FILE random rows from every CDSCO PDF (smaller files whole), drawn with a fixed
seed, so it is reproducible and covers every month and layout family: 309 rows.

SPLIT: train / validation / test, fixed when the sample is drawn and by WHOLE PDF, so rows of a
test-split file are never seen in training (Phase 10; CLAUDE.md §5: the test split is never used for
training or tuning). Recording it up front means it can't be chosen later to flatter a result.

ROW ID: what the PDF itself prints: the file's SHA-256, the page the row starts on, and its S.No.
(S.No alone repeats inside some files; with the page it is unique across the archive.) A label
therefore survives parser changes: if a change loses a row, its label is unmatched and step 8
counts it as a miss, instead of the labels silently shifting onto the wrong rows.

Files (paths relative to extraction/, where the commands run):
- eval/manifest.csv (committed): the sample and its split. Row IDs only, no CDSCO text (ADR 0003).
- ../data/eval-set/labels.jsonl (git-ignored; keep a private backup): the labels, one JSON per line.

Draw the sample once (from extraction/, RustFS up); it refuses to overwrite an existing manifest:
    uv run --env-file ../.env python -m drugwatch_extraction.eval_set --sample
"""

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from drugwatch_extraction.bronze import BUCKET, read_bronze
from drugwatch_ingestion.store import RawStore

SEED = 2026
PER_FILE = 12
# Ties go to the first name: a family with two PDFs then gets one in train and one in test.
SPLIT_SHARES = (("test", 0.2), ("validation", 0.2), ("train", 0.6))
MANIFEST = Path("eval/manifest.csv")
LABELS = Path("../data/eval-set/labels.jsonl")
MANIFEST_COLUMNS = ("source_sha256", "page", "serial_no", "row_index", "family", "split",
                    "source_dataset", "alert_month", "file_id", "source_key")  # fmt: skip

RowId = tuple[str, int, str]  # (source_sha256, page, S.No)


def row_id(row: dict[str, Any]) -> RowId:
    return row["source_sha256"], int(row["page"]), str(row["serial_no"]).strip().rstrip(".")


def sample_rows(files: list[list[dict]], per_file: int = PER_FILE, seed: int = SEED) -> list[dict]:
    """Up to per_file random records from each PDF's records, in document order."""
    rng = random.Random(seed)  # noqa: S311 (a reproducible sample, not security)
    sampled = []
    # A fixed order of files and rows, so the same seed always draws the same rows.
    for records in sorted((f for f in files if f), key=lambda rows: rows[0]["source_key"]):
        records = sorted(records, key=lambda r: r["row_index"])
        chosen = rng.sample(records, min(per_file, len(records)))
        sampled += sorted(chosen, key=lambda r: r["row_index"])
    ids = Counter(row_id(r) for r in sampled)
    if duplicates := [i for i, n in ids.items() if n > 1]:
        raise ValueError(f"row IDs not unique: {duplicates[:3]}")
    return sampled


def assign_splits(sampled: list[dict], seed: int = SEED) -> dict[str, str]:
    """source_sha256 -> split. Whole PDFs, family by family: each PDF (in a seeded random order)
    goes to the split furthest below its target share of that family's sampled rows."""
    rng = random.Random(seed)  # noqa: S311
    rows_per_file: dict[str, Counter] = defaultdict(Counter)
    for row in sampled:
        rows_per_file[row["family"]][row["source_sha256"]] += 1
    split_of = {}
    for family in sorted(rows_per_file):
        files = sorted(rows_per_file[family])
        rng.shuffle(files)
        total = sum(rows_per_file[family].values())
        given: Counter = Counter()
        for sha in files:
            name = max(SPLIT_SHARES, key=lambda split: split[1] * total - given[split[0]])[0]
            split_of[sha] = name
            given[name] += rows_per_file[family][sha]
    return split_of


def manifest_rows(sampled: list[dict], split_of: dict[str, str]) -> list[dict]:
    return [
        {
            **{column: r.get(column) for column in MANIFEST_COLUMNS},
            "serial_no": row_id(r)[2],  # digits only: "8." -> "8"
            "split": split_of[r["source_sha256"]],
        }
        for r in sampled
    ]


def write_manifest(path: Path, rows: list[dict]) -> None:
    if path.exists():  # the split must stay fixed once labelling has started
        raise FileExistsError(
            f"{path} exists: the sample and split are fixed. To redraw, delete it deliberately "
            "and record why in PROGRESS.md."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_manifest(path: Path = MANIFEST) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{**row, "page": int(row["page"])} for row in csv.DictReader(f)]


def load_labels(path: Path = LABELS) -> dict[RowId, dict]:
    """The latest label of each row (labelling a row again replaces the earlier label)."""
    labels: dict[RowId, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                label = json.loads(line)
                labels[row_id(label)] = label
    return labels


def append_label(path: Path, label: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(label, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())  # on disk before the next row starts: a crash loses at most one row


def bronze_files(s3: Any, prefix: str = "cdsco-pdf/") -> list[list[dict]]:
    """Every bronze PDF file's records (not cdsco-portal/: the eval set is about PDF extraction;
    portal rows have no `page`, so row_id() would fail on them)."""
    keys = [
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".parquet")
    ]
    return [read_bronze(s3, key).to_pylist() for key in sorted(keys)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Draw the eval-set sample and split (once).")
    parser.add_argument("--sample", action="store_true", required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args(argv)

    sampled = sample_rows(bronze_files(RawStore.from_env().s3))
    split_of = assign_splits(sampled)
    rows = manifest_rows(sampled, split_of)
    try:
        write_manifest(args.manifest, rows)
    except FileExistsError as error:
        sys.exit(str(error))
    print(f"{len(rows)} rows from {len(split_of)} PDFs -> {args.manifest}")
    for split, _ in SPLIT_SHARES:
        part = [r for r in rows if r["split"] == split]
        families = dict(sorted(Counter(r["family"] for r in part).items()))
        pdfs = len({r["source_sha256"] for r in part})
        print(f"  {split:10} {len(part):3} rows, {pdfs:2} PDFs, by family {families}")


if __name__ == "__main__":
    main()
