"""Phase 10 step 1: the fine-tuning set - a row's raw text in, its fields out.

INPUT: the header row's words, then the row's own words, exactly as pdfplumber reads them off the
page, in reading order, with **no column assignment**. The rule parser already knows which x-range
is which column; the LLM is only worth building if it can recover the fields WITHOUT that crutch,
so training it on the parser's column-aligned cells would teach it the one skill it doesn't need.
Row boundaries come from `second_reader.row_strips()` (Phase 2, already used to crop the label
pictures) - a header strip, the row's own strip (plus any unnumbered continuation cell under it,
e.g. a split pack), and any later page it continues onto.

OUTPUT: the row's fields - a label where one exists (the labelled eval set, ANY split), otherwise
the parser's own value where the parser was HIGH confidence. Low-confidence, unlabelled rows are
left out: nobody has checked what they should say.

SCOPE: train-split PDFs only (ADR 0019, CLAUDE.md §5: the test and validation splits are never
used for training). Family E is left out entirely, even though it is a train-split family: its
vaccine batches are near-copies of family A's, which DOES appear in validation/test, so training
on E would let the model memorise answers that look like a real validation/test row rather than
reading one.

Run (from llm/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_llm.training_data
"""

import argparse
import io
import json
import os
from pathlib import Path
from typing import Any

import pdfplumber

from drugwatch_extraction import family_a, family_b, family_c, family_d, family_f
from drugwatch_extraction.confidence import REQUIRED
from drugwatch_extraction.eval_set import bronze_files, load_labels, row_id
from drugwatch_extraction.second_reader import row_strips
from drugwatch_extraction.table_parser import Vocabulary
from drugwatch_ingestion.store import RawStore

OUT_PATH = Path("../data/llm-training/train.jsonl")  # real CDSCO text: git-ignored (ADR 0003)

EXCLUDED_FAMILY = "E"  # Phase 2's caution (docs/eval-set.md): near-duplicates of family A

# Deliberately no "E" here: a KeyError below would mean a family-E row slipped past the filter,
# which is a louder failure than a silently wrong vocabulary.
VOCABULARIES: dict[str, Vocabulary] = {
    "A": family_a.VOCABULARY,
    "B": family_b.VOCABULARY,
    "C": family_c.VOCABULARY,
    "D": family_d.VOCABULARY,
    "F": family_f.VOCABULARY,
}


def row_text(document: Any, page_no: int, serial: str, pages: list[int], family: str) -> str:
    """The header strip's words, then the row's own strip(s)' words, each in reading order (top
    to bottom, then left to right) - one line per strip, exactly as `row_strips` cut the label
    pictures, so a human checking this against a label's picture is checking the same region."""
    strips = row_strips(document, page_no, serial, pages, VOCABULARIES[family])
    lines = []
    for number, (x0, top, x1, bottom) in strips:
        page = document.pages[number - 1]
        words = page.crop((x0, top, x1, bottom)).extract_words()
        words.sort(key=lambda w: (round(w["top"]), w["x0"]))
        lines.append(" ".join(w["text"] for w in words))
    return "\n".join(lines)


def target_fields(record: dict[str, Any], label: dict[str, Any] | None) -> dict[str, str] | None:
    """What the model should learn to output for this row, or None to skip it. A label (ground
    truth, from the eval set's double reading) is always used if every field was readable. Failing
    that, the parser's own value is used, but only where the parser itself was high confidence -
    an unlabelled low-confidence row's true value is simply unknown."""
    fields = REQUIRED.get(record["family"], ())
    if label is not None:
        values = label["fields"]
        if any(values.get(f) is None for f in fields):  # "/u": unreadable, not trustworthy enough
            return None
        return {f: values.get(f, "") for f in fields}
    if record.get("confidence") != "high":
        return None
    return {f: (record.get(f) or "") for f in fields}


def build_examples(
    manifest: list[dict[str, Any]], labels: dict[tuple, dict], s3: Any
) -> list[dict[str, Any]]:
    train_shas = {r["source_sha256"] for r in manifest if r["split"] == "train"}
    examples = []
    skipped_unusable = 0
    for records in bronze_files(s3):
        if not records or records[0]["source_sha256"] not in train_shas:
            continue
        if records[0]["family"] == EXCLUDED_FAMILY:
            continue
        key = records[0]["source_key"]
        # raw/ is never modified (CLAUDE.md §5); this only reads it, the same call extract.py uses.
        pdf_bytes = s3.get_object(Bucket="raw", Key=key)["Body"].read()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            for record in records:
                label = labels.get(row_id(record))
                fields = target_fields(record, label)
                if fields is None:
                    skipped_unusable += 1
                    continue
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
                        "label_source": "labelled"
                        if label is not None
                        else "parser_high_confidence",
                    }
                )
    return examples, skipped_unusable


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build Phase 10's LoRA training set.")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    from drugwatch_extraction.eval_set import read_manifest

    # eval_set.MANIFEST is relative to extraction/, where its own CLI runs; this one runs from
    # llm/, so the same file is reached from here instead of trusting that constant's cwd.
    manifest = read_manifest(Path("../extraction/eval/manifest.csv"))
    labels = load_labels()
    s3 = RawStore.from_env().s3

    examples, skipped = build_examples(manifest, labels, s3)

    # Leakage check, right here rather than only in a test: refuse to write a file that could not
    # have come from train-split, non-family-E PDFs.
    train_shas = {r["source_sha256"] for r in manifest if r["split"] == "train"}
    bad_family = [e for e in examples if e["family"] == EXCLUDED_FAMILY]
    if bad_family:
        raise RuntimeError(f"{len(bad_family)} family-E examples leaked into the training set")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

    labelled = sum(1 for e in examples if e["label_source"] == "labelled")
    print(f"{len(examples)} training examples -> {args.out}")
    print(
        f"  {labelled} from labels, {len(examples) - labelled} from high-confidence parser output"
    )
    print(f"  {skipped} rows skipped: unlabelled and not high-confidence, or an unreadable label")
    print(f"  from {len(train_shas)} train-split PDFs, family E excluded")


if __name__ == "__main__":
    main()
