"""Phase 10 step 2's evaluation rows: validation-split, labelled rows only.

Unlike `training_data.py`, this is never used to teach a model anything - it exists to SCORE
candidate models before any fine-tuning happens, so the only acceptable ground truth is a human
(or AI-assisted double-reading) label, never the rule parser's own output. Scoring a model against
the parser would be circular: a model that just copies the parser's mistakes would look perfect.

Family E never appears in validation or test (docs/eval-set.md: "Families E and F have one PDF
each, so they are only in train"), so there is nothing to additionally exclude here - unlike
`training_data.py`, which has to filter it out of the TRAIN split on purpose. A check still runs,
because "it can't happen" is exactly the kind of thing worth not just assuming.

Run (from llm/, RustFS up, the labelled eval set present on this Mac):
    uv run --env-file ../.env python -m drugwatch_llm.validation_data
"""

import io
import json
from pathlib import Path
from typing import Any

import pdfplumber

from drugwatch_extraction.confidence import REQUIRED
from drugwatch_extraction.eval_set import bronze_files, load_labels, read_manifest, row_id
from drugwatch_ingestion.store import RawStore
from drugwatch_llm.training_data import row_text

MANIFEST_PATH = Path("../extraction/eval/manifest.csv")
OUT_PATH = Path("../data/llm-training/validation.jsonl")  # real CDSCO text: git-ignored (ADR 0003)


def label_fields(record: dict[str, Any], label: dict[str, Any]) -> dict[str, str] | None:
    """The label's fields for this row's family, or None if any required field is unreadable."""
    fields = REQUIRED.get(record["family"], ())
    values = label["fields"]
    if any(values.get(f) is None for f in fields):
        return None
    return {f: values.get(f, "") for f in fields}


def build_examples(
    manifest: list[dict[str, Any]], labels: dict[tuple, dict], s3: Any
) -> list[dict[str, Any]]:
    validation_shas = {r["source_sha256"] for r in manifest if r["split"] == "validation"}

    examples = []
    for records in bronze_files(s3):
        if not records or records[0]["source_sha256"] not in validation_shas:
            continue
        key = records[0]["source_key"]
        pdf_bytes = s3.get_object(Bucket="raw", Key=key)["Body"].read()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            for record in records:
                label = labels.get(row_id(record))
                if label is None:
                    continue  # not a sampled-and-labelled row: no ground truth to score against
                fields = label_fields(record, label)
                if fields is None:
                    continue  # an unreadable ("/u") field: no trustworthy ground truth
                serial = (record.get("serial_no") or "").strip().rstrip(".")
                text = row_text(
                    document, record["page"], serial, list(record["pages"]), record["family"]
                )
                examples.append(
                    {
                        "text": text,
                        "fields": fields,
                        "source_key": key,
                        "page": record["page"],
                        "row_index": record["row_index"],
                        "family": record["family"],
                    }
                )
    return examples


def main() -> None:
    manifest = read_manifest(MANIFEST_PATH)
    labels = load_labels()
    s3 = RawStore.from_env().s3

    examples = build_examples(manifest, labels, s3)
    bad_family = {e["family"] for e in examples} & {"E"}
    if bad_family:
        raise RuntimeError("family E should never appear in validation/test (docs/eval-set.md)")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
    print(f"{len(examples)} validation examples -> {OUT_PATH}")


if __name__ == "__main__":
    main()
