"""Unit tests for what goes into the training set, and what is deliberately left out.

No real CDSCO text here (ADR 0003): these exercise `target_fields`'s decision logic with made-up
field values, not the real archive. The row-text extraction itself (`row_text`, needing a real PDF
from RustFS) is exercised by actually running `training_data.py` against the stack, the same way
`extraction/`'s own parsers are proven against real PDFs rather than in a unit test.
"""

import csv
import json
from pathlib import Path

import pytest

from drugwatch_llm.training_data import EXCLUDED_FAMILY, target_fields


def test_a_label_is_used_even_when_the_parser_was_low_confidence():
    # The label is ground truth; the confidence flag describes the PARSER, not the label.
    record = {"family": "B", "confidence": "low"}
    label = {
        "fields": {
            "product_name": "X",
            "batch_no": "Y",
            "mfg_date": "09/2024",
            "expiry_date": "08/2026",
            "manufacturer": "Z",
            "failure_reason": "Assay",
        }
    }
    assert target_fields(record, label) is not None


def test_an_unreadable_label_field_is_not_trustworthy_enough_to_train_on():
    record = {"family": "B", "confidence": "high"}
    label = {
        "fields": {
            "product_name": "X",
            "batch_no": None,  # "/u" in the labelling tool: the second reader couldn't read it
            "mfg_date": "09/2024",
            "expiry_date": "08/2026",
            "manufacturer": "Z",
            "failure_reason": "Assay",
        }
    }
    assert target_fields(record, label) is None


def test_a_blank_cell_label_is_still_usable():
    # "/b" in the labelling tool: the cell really is empty. That is a known, correct answer -
    # unlike "/u", which means nobody knows what the cell says.
    record = {"family": "F", "confidence": "high"}  # family F has no failure_reason at all
    label = {
        "fields": {
            "product_name": "X",
            "batch_no": "Y",
            "mfg_date": "09/2024",
            "expiry_date": "",  # blank
            "manufacturer": "Z",
        }
    }
    fields = target_fields(record, label)
    assert fields == {
        "product_name": "X",
        "batch_no": "Y",
        "mfg_date": "09/2024",
        "expiry_date": "",
        "manufacturer": "Z",
    }
    assert "failure_reason" not in fields  # family F genuinely has no such column


def test_an_unlabelled_low_confidence_row_is_left_out():
    # Nobody has checked what this row should say - using the parser's own guess here would train
    # the model on an answer that might be exactly the mistake Phase 10 exists to catch.
    record = {"family": "B", "confidence": "low", "product_name": "whatever the parser saw"}
    assert target_fields(record, None) is None


def test_an_unlabelled_high_confidence_row_uses_the_parsers_value():
    record = {
        "family": "B",
        "confidence": "high",
        "product_name": "X",
        "batch_no": "Y",
        "mfg_date": "09/2024",
        "expiry_date": "08/2026",
        "manufacturer": "Z",
        "failure_reason": "Assay",
    }
    assert target_fields(record, None) == {
        "product_name": "X",
        "batch_no": "Y",
        "mfg_date": "09/2024",
        "expiry_date": "08/2026",
        "manufacturer": "Z",
        "failure_reason": "Assay",
    }


def test_a_missing_parser_field_becomes_an_empty_string_not_none():
    # JSON output and the grounding check (step 3) both need a string per field, never a null.
    record = {"family": "B", "confidence": "high", "product_name": "X"}
    fields = target_fields(record, None)
    assert fields["batch_no"] == ""


def test_excluded_family_is_e():
    # If this ever changes, it changes the leakage argument in ADR 0019 and docs/eval-set.md, not
    # just a constant - so a future edit here should be a deliberate, documented one.
    assert EXCLUDED_FAMILY == "E"


def test_no_leaked_pdf_in_the_real_training_file():
    """The one check the plan step itself asks for: no validation/test-split PDF, and no family-E
    row, actually landed in the training file written to disk.

    Skipped if that file doesn't exist (CI, or before step 1 has been run here) - this test is
    about catching a leak in a REAL run, not about requiring one to exist."""
    train_file = Path("../data/llm-training/train.jsonl")
    manifest_file = Path("../extraction/eval/manifest.csv")
    if not train_file.exists() or not manifest_file.exists():
        pytest.skip("no real training file on this machine yet (run training_data.py)")

    with manifest_file.open(newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))
    train_shas = {r["source_sha256"] for r in manifest if r["split"] == "train"}

    with train_file.open(encoding="utf-8") as f:
        examples = [json.loads(line) for line in f if line.strip()]
    assert examples, "the training file is empty"

    leaked_family = {e["family"] for e in examples} & {EXCLUDED_FAMILY}
    assert not leaked_family, f"family {EXCLUDED_FAMILY} should never appear in training examples"

    for example in examples:
        sha = example["source_key"].rsplit("/", 1)[-1].removesuffix(".pdf")
        assert sha in train_shas, f"{example['source_key']} is not a train-split PDF"
