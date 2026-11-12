"""evaluate.py: the scoring rules (made-up values), and the baseline as a regression guard."""

import os

import pytest

from drugwatch_extraction.eval_set import LABELS, MANIFEST, load_labels, read_manifest, row_id
from drugwatch_extraction.evaluate import Counts, evaluate, load_records, outcome
from drugwatch_ingestion.store import RawStore


@pytest.mark.parametrize(
    ("label", "parsed", "expected"),
    [
        ("TB-1201", "TB-\n1201", "TP"),  # line breaks and spaces don't count
        ("TB-1201", "TB-1207", "FP+FN"),  # wrong: invented and missed
        ("TB-1201", "", "FN"),  # missed
        ("TB-1201", None, "FN"),  # no such field / the row was lost
        ("", "TB-1201", "FP"),  # the cell is blank, the parser invented a value
        ("", "", "TN"),
        (None, "anything", None),  # unreadable label: not scored
        ("Assay", "assay", "FP+FN"),  # case counts
    ],
)
def test_one_value(label, parsed, expected):
    assert outcome(label, parsed) == expected


def test_precision_recall_and_f1():
    counts = Counts()
    for result in ("TP", "TP", "TP", "FP+FN", "FN", "TN"):
        counts.add(result)

    assert (counts.tp, counts.fp, counts.fn, counts.tn) == (3, 1, 2, 1)
    assert counts.precision == 3 / 4
    assert counts.recall == 3 / 5
    assert counts.f1 == pytest.approx(2 * 0.75 * 0.6 / (0.75 + 0.6))
    assert Counts().f1 == 0.0  # nothing scored: no division by zero


def test_a_lost_row_counts_every_labelled_value_as_missed():
    item = {"source_sha256": "a" * 64, "page": 1, "serial_no": "1", "family": "B", "split": "test"}
    labels = {row_id(item): {**item, "fields": {"batch_no": "TB1", "mfg_date": ""}}}

    result = evaluate([item], labels, records={})  # the parser has no record for this row

    overall = result["groups"]["overall"]["all"]
    assert (overall.tp, overall.fp, overall.fn, overall.tn) == (0, 0, 1, 1)
    assert result["errors"][0]["confidence"] == "row lost"


def test_results_are_grouped_by_field_family_split_and_confidence():
    item = {"source_sha256": "a" * 64, "page": 1, "serial_no": "1", "family": "B", "split": "test"}
    labels = {row_id(item): {**item, "fields": {"batch_no": "TB1", "product_name": "Tablet"}}}
    records = {row_id(item): {"batch_no": "TB1", "product_name": ". Tablet", "confidence": "high"}}

    groups = evaluate([item], labels, records)["groups"]

    assert groups["field"]["batch_no"].tp == 1
    assert groups["field"]["product_name"].fn == 1
    assert groups["split"]["test"].tp == 1 and groups["confidence"]["high"].fp == 1


@pytest.mark.integration
@pytest.mark.skipif(
    "RUSTFS_ACCESS_KEY" not in os.environ or not LABELS.exists(),
    reason="needs RustFS and the labels",
)
def test_the_parser_stays_at_or_above_its_recorded_baseline():
    # Regression guard (plan §16): a parser change must not lower the step-8 baseline.
    manifest = read_manifest(MANIFEST)
    labels = load_labels(LABELS)
    result = evaluate(manifest, labels, load_records(RawStore.from_env().s3, manifest))

    overall = result["groups"]["overall"]["all"]
    assert len(labels) == 309
    assert overall.f1 >= BASELINE_F1


BASELINE_F1 = 0.996  # step-8 baseline, 2026-11-12: 99.62% (extraction report §3)
