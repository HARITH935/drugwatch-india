"""Phase 10 step 6: the LLM fallback as a real pipeline task.

Runs AFTER `drugwatch_extraction.bronze --all` (needs the rule parser's bronze already written)
and BEFORE Spark reads bronze (Phase 3's `build_silver` must see any correction, not the rule
parser's original miss). `extraction/` stays exactly as Phase 2 left it - closed, and unaware
`llm/` exists at all; this reads and rewrites bronze from the outside, the same bucket
`bronze.py` already writes to, through the same `write_bronze`/`read_bronze` it uses.

For each bronze PDF file, in two passes so a quiet month (most of them - the archive has
~103 low-confidence rows in total, "a handful a month") never has to load a 1.5B model at all:

1. SCAN every file's records for a correctable candidate: `confidence == "low"` (the row-level
   flag the plan calls "low-confidence rows" everywhere else) AND not a multi-part pack
   (`validator.is_unsplittable_multi_part` - step 5 measured that shape make things worse, not
   better, and refuses it before the model is ever asked, not just before its answer is used).
2. Only if at least one candidate exists ANYWHERE does this load the registered adapter
   (`registry.load`) and process every file that has one: open its raw/ PDF (never modified -
   CLAUDE.md §5), build each candidate row's text, generate, and `validator.merge` with the
   row's own real warnings. A row whose merge changed anything gets `extraction_method = "llm"`
   (plan step 6's own wording: mark the ROW, not the field) and its `confidence`/
   `confidence_reasons` recomputed (`confidence.assess`) against its now-current values, not
   left stale from before the correction. Every other record in that file - every row this
   pass never touches - is written back byte-for-byte unchanged, because `write_bronze`
   replaces the WHOLE file (ADR 0007): a partial rewrite would silently drop the untouched rows.

Run (from llm/, RustFS + MLflow up, a registered adapter at the "production" alias):
    uv run --env-file ../.env python -m drugwatch_llm.fallback --all
    uv run --env-file ../.env python -m drugwatch_llm.fallback --all --dry-run   # preview only
"""

import argparse
import io
import sys
from dataclasses import dataclass
from typing import Any

import pdfplumber

from drugwatch_extraction import family_a, family_b, family_c, family_d, family_e, family_f
from drugwatch_extraction.bronze import BUCKET, read_bronze, write_bronze
from drugwatch_extraction.confidence import REQUIRED, assess
from drugwatch_extraction.extract import ExtractionResult
from drugwatch_extraction.table_parser import Vocabulary
from drugwatch_ingestion.store import RawStore
from drugwatch_llm.prompting import build_prompt
from drugwatch_llm.training_data import row_text
from drugwatch_llm.validator import is_unsplittable_multi_part, low_confidence_fields, merge
from drugwatch_llm.zero_shot import device_for, generate

# The COMPLETE family map, unlike training_data.VOCABULARIES: that one deliberately excludes "E"
# (a leakage guard for training only), but this is production inference over the whole archive,
# where a family-E row can be genuinely low-confidence and deserves the same fallback as any other.
VOCABULARIES: dict[str, Vocabulary] = {
    "A": family_a.VOCABULARY,
    "B": family_b.VOCABULARY,
    "C": family_c.VOCABULARY,
    "D": family_d.VOCABULARY,
    "E": family_e.VOCABULARY,
    "F": family_f.VOCABULARY,
}


@dataclass
class FileResult:
    key: str
    rows_considered: int = 0
    rows_changed: int = 0
    rows_skipped_multi_part: int = 0


def bronze_pdf_keys(s3: Any, prefix: str = "cdsco-pdf/") -> list[str]:
    """Every bronze PDF file's key, sorted - the same listing `eval_set.bronze_files` does,
    kept separate here so this can read one file at a time instead of all of them at once."""
    return sorted(
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".parquet")
    )


def is_candidate(record: dict[str, Any]) -> bool:
    """A row worth asking the model about: the parser itself is unsure, and it isn't the one
    shape (step 5) measured to make the fallback worse rather than better."""
    return record.get("confidence") == "low" and not is_unsplittable_multi_part(
        record.get("warnings") or []
    )


def apply_merge_to_row(record: dict[str, Any], reply: str, text: str) -> bool:
    """`validator.merge` plus what the pipeline does with its answer - factored out of
    `apply_fallback_to_row` so this part (the only part with a decision in it) is testable with
    a made-up `reply`, no model needed, the same way `evaluate.score_one` is. Returns whether
    anything actually changed (so the caller only re-marks `extraction_method` and re-runs
    `assess` when it needs to - most low-confidence rows are the PDF printing nothing, which the
    LLM correctly leaves blank too, and that is not a change worth recomputing anything over)."""
    family = record["family"]
    low_fields = set(low_confidence_fields(record))
    before = {f: record.get(f) or "" for f in REQUIRED.get(family, ())}
    merged = merge(before, reply, family, text, low_fields, record.get("warnings") or [])
    if merged == before:
        return False
    record.update(merged)
    record["extraction_method"] = "llm"
    record["confidence"], record["confidence_reasons"] = assess(record)
    return True


def apply_fallback_to_row(record: dict[str, Any], text: str, model, tokenizer, device: str) -> bool:
    """Generate a reply for real, then `apply_merge_to_row`."""
    reply = generate(model, tokenizer, build_prompt(text, record["family"]), device)
    return apply_merge_to_row(record, reply, text)


def process_file(
    s3: Any, key: str, records: list[dict[str, Any]], candidate_indices: list[int], model,
    tokenizer, device: str,
) -> FileResult:  # fmt: skip
    """One bronze file's worth of work: open its PDF once, correct every candidate row in it,
    and write the WHOLE file back if anything changed."""
    result = FileResult(key=key, rows_considered=len(candidate_indices))
    source_key = records[0]["source_key"]
    pdf_bytes = s3.get_object(Bucket="raw", Key=source_key)["Body"].read()
    changed = False
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for index in candidate_indices:
            record = records[index]
            serial = (record.get("serial_no") or "").strip().rstrip(".")
            text = row_text(
                document, record["page"], serial, list(record["pages"]), record["family"],
                vocabularies=VOCABULARIES,
            )  # fmt: skip
            if apply_fallback_to_row(record, text, model, tokenizer, device):
                changed = True
                result.rows_changed += 1
    if changed:
        write_bronze(s3, ExtractionResult(key=source_key, records=records))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 10 step 6: the LLM fallback, for real.")
    parser.add_argument("--all", action="store_true", required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change; write nothing"
    )
    args = parser.parse_args(argv)

    s3 = RawStore.from_env().s3
    keys = bronze_pdf_keys(s3)
    print(f"{len(keys)} bronze PDF files")

    # Pass 1: find every candidate without loading anything heavier than Parquet.
    files: list[tuple[str, list[dict[str, Any]], list[int]]] = []
    skipped_multi_part = 0
    for key in keys:
        records = read_bronze(s3, key).to_pylist()
        multi_part = sum(
            1
            for r in records
            if r.get("confidence") == "low" and is_unsplittable_multi_part(r.get("warnings") or [])
        )
        skipped_multi_part += multi_part
        candidates = [i for i, r in enumerate(records) if is_candidate(r)]
        if candidates:
            files.append((key, records, candidates))

    total_candidates = sum(len(c) for _, _, c in files)
    print(f"{total_candidates} candidate row(s) across {len(files)} file(s)")
    print(f"{skipped_multi_part} multi-part-pack row(s) never offered to the model")
    if not files:
        print("nothing to do - no model loaded")
        return 0

    if args.dry_run:
        for key, _, candidates in files:
            print(f"  would consider {len(candidates)} row(s) in {key}")
        print("\n--dry-run: nothing written")
        return 0

    from drugwatch_llm import registry

    device = device_for()
    loaded = registry.load(device)
    print(f"loaded {loaded.describe()}, device={device}")

    total_changed = 0
    for key, records, candidates in files:
        result = process_file(s3, key, records, candidates, loaded.model, loaded.tokenizer, device)
        total_changed += result.rows_changed
        print(f"  {key}: {result.rows_changed}/{result.rows_considered} row(s) changed")

    print(f"\n{total_changed} row(s) now extraction_method='llm'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
