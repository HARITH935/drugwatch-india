"""One entry point for every CDSCO alert PDF: classify, parse, attach provenance (Phase 2 step 4).

    extract_pdf(s3, key)  ->  ExtractionResult with one RECORD per row

A record is a flat dict: the row's fields as extracted (see rows.py), plus where it came from
(CLAUDE.md §5: every row keeps its source file, page, row index, source URL and extraction_method):
- source_key, source_sha256: the PDF in raw/ (content-addressed, so the hash names the exact bytes);
- source_url: the CDSCO URL the PDF was downloaded from (the "link to the original document", §6);
- source_dataset, alert_month, file_id, listing_title: what CDSCO's alerts page said about the file;
- family, page, pages, row_index, section: where in the file the row sits;
- extraction_method: "rule" (Phase 10's LLM fallback will write "llm");
- warnings: problems known for this row (the step-5 confidence flag reads them).

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.extract --all
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from drugwatch_extraction import __version__
from drugwatch_extraction.classify import classify_pdf
from drugwatch_extraction.family_a import parse_family_a
from drugwatch_extraction.family_b import parse_family_b
from drugwatch_extraction.family_c import parse_family_c
from drugwatch_extraction.family_d import parse_family_d
from drugwatch_extraction.family_e import parse_family_e
from drugwatch_extraction.family_f import parse_family_f
from drugwatch_extraction.rows import ParseResult
from drugwatch_ingestion.store import META_SUFFIX, RawStore

PARSERS: dict[str, Callable[[bytes], ParseResult]] = {
    "A": parse_family_a,
    "B": parse_family_b,
    "C": parse_family_c,
    "D": parse_family_d,
    "E": parse_family_e,
    "F": parse_family_f,
}


@dataclass
class ExtractionResult:
    key: str
    family: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    parse: ParseResult | None = None  # the parser's report: skipped rows, gaps, warnings
    problem: str | None = None  # set when the file couldn't be extracted at all


def records_for(data: bytes, sidecar: dict[str, Any]) -> ExtractionResult:
    """The pure core: PDF bytes and their raw/ sidecar in, records out. No storage access."""
    key = sidecar["key"]
    result = ExtractionResult(key=key)
    if hashlib.sha256(data).hexdigest() != sidecar["sha256"]:
        result.problem = "bytes don't match the sidecar's SHA-256: provenance would be wrong"
        return result
    classified = classify_pdf(data)
    result.family = classified.family
    if classified.family not in PARSERS:
        result.problem = f"layout family {classified.family!r}: no parser"
        return result
    if not classified.readable:
        result.problem = f"{classified.page_kinds['scanned']} scanned page(s) need OCR"
        return result

    parse = PARSERS[classified.family](data)
    result.parse = parse
    warnings_by_row: dict[int, list[str]] = {}
    for row_index, message in parse.warnings:
        warnings_by_row.setdefault(row_index, []).append(message)
    provenance = {
        "source_key": key,
        "source_sha256": sidecar["sha256"],
        "source_url": sidecar.get("request", {}).get("final_url"),
        "source_dataset": sidecar.get("dataset"),
        "alert_month": sidecar.get("alert_month"),
        "file_id": sidecar.get("file_id"),
        "listing_title": sidecar.get("listing", {}).get("title"),
        "family": classified.family,
        "extraction_method": "rule",
        "extractor_version": __version__,  # which parser code produced the record
    }
    for row in parse.rows:
        result.records.append(
            {
                **row.fields,
                **provenance,
                "page": row.page,
                "pages": list(row.pages),
                "row_index": row.row_index,
                "section": row.section,
                "warnings": warnings_by_row.get(row.row_index, []),
            }
        )
    return result


def extract_pdf(s3: Any, key: str, bucket: str = "raw") -> ExtractionResult:
    """Load a PDF and its sidecar from raw/ and extract it."""
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    sidecar = json.loads(s3.get_object(Bucket=bucket, Key=key + META_SUFFIX)["Body"].read())
    return records_for(data, sidecar)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Extract rows from CDSCO alert PDFs in raw/.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--key", help="one PDF's raw/ key")
    which.add_argument("--all", action="store_true", help="every PDF under cdsco-pdf/")
    parser.add_argument("--show", type=int, default=0, help="print the first N records as JSON")
    args = parser.parse_args(argv)

    s3 = RawStore.from_env().s3
    if args.all:
        keys = sorted(
            obj["Key"]
            for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket="raw", Prefix="cdsco-pdf/"
            )
            for obj in page.get("Contents", [])
            if obj["Key"].endswith(".pdf")
        )
    else:
        keys = [args.key]

    records, families, problems, warned = [], Counter(), [], 0
    for key in keys:
        result = extract_pdf(s3, key)
        if result.problem:
            problems.append(f"{key}: {result.problem}")
            continue
        families[result.family] += len(result.records)
        warned += sum(1 for record in result.records if record["warnings"])
        records += result.records
    print(
        f"{len(keys)} PDFs -> {len(records)} records; by family: {dict(sorted(families.items()))}"
    )
    print(f"records with warnings: {warned}")
    for record in records[: args.show]:
        print(json.dumps(record, ensure_ascii=False, indent=1))
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)


if __name__ == "__main__":
    main()
