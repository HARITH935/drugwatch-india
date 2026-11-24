"""Phase 10 step 5's own arithmetic: no real CDSCO text (ADR 0003), no real model - made-up rows
and made-up replies, the same way `test_validator.py` exercises `merge` without one. The real test
split's row-text extraction and the adapter's real generations are exercised by actually running
`evaluate.py` against the stack, not here.
"""

import json
from pathlib import Path

import pytest

from drugwatch_llm.evaluate import ScoreSet, low_confidence_fields, score_one

B_FIELDS = ("product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer", "failure_reason")


def _reply(**fields) -> str:
    base = dict.fromkeys(B_FIELDS, "")
    base.update(fields)
    return json.dumps(base)


def _example(**overrides) -> dict:
    base = {
        "text": "Batch No: TB-1201 Mfg 09/2024",
        "family": "B",
        "fields": dict.fromkeys(B_FIELDS, ""),
        "parser_fields": dict.fromkeys(B_FIELDS, ""),
        "low_confidence_fields": [],
        "confidence": "high",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ low_confidence_fields


def test_low_confidence_fields_matches_field_problem_not_the_row_flag():
    # A record can be row-level "low" for a reason with no single field (confidence.py's "parser
    # warning"), while every individual field is well-formed - D4 cares about the field, not the
    # row, so this must come back empty rather than flagging everything because the row is "low".
    record = {
        "family": "B",
        "product_name": "Zyntophil",
        "batch_no": "TB-1201",
        "mfg_date": "09/2024",
        "expiry_date": "08/2026",
        "manufacturer": "Marvex Labs",
        "failure_reason": "Assay",
        "warnings": ["some unrelated parser warning"],
    }
    assert low_confidence_fields(record) == []


def test_low_confidence_fields_finds_exactly_the_bad_ones():
    record = {
        "family": "B",
        "product_name": "Zyntophil",
        "batch_no": "",  # missing
        "mfg_date": "45/2024",  # not a date
        "expiry_date": "08/2026",
        "manufacturer": "Marvex Labs",
        "failure_reason": "Assay",
    }
    assert low_confidence_fields(record) == ["batch_no", "mfg_date"]


def test_low_confidence_fields_respects_the_familys_own_required_list():
    # Family F has no failure_reason column at all (confidence.REQUIRED); a blank one there is
    # not a missing field, because the column doesn't exist for F in the first place.
    record = {
        "family": "F",
        "product_name": "Zyntophil",
        "batch_no": "TB-1201",
        "mfg_date": "09/2024",
        "expiry_date": "08/2026",
        "manufacturer": "Marvex Labs",
    }
    assert low_confidence_fields(record) == []


# ------------------------------------------------------------------ score_one


def test_a_correct_merge_counts_as_a_true_positive_both_ways():
    example = _example(
        fields={**dict.fromkeys(B_FIELDS, ""), "batch_no": "TB-1201"},
        parser_fields={**dict.fromkeys(B_FIELDS, ""), "batch_no": "TB-1201"},
        confidence="high",
    )
    baseline, merged = ScoreSet(), ScoreSet()
    out = score_one(example, _reply(batch_no="TB-1201"), baseline, merged)
    assert baseline.overall.tp == 1 and baseline.overall.fp == 0 and baseline.overall.fn == 0
    assert merged.overall.tp == 1
    assert out["substitutions"] == []  # the LLM agreed; nothing actually changed
    assert out["schema_exact"] is True


def test_the_llm_fixing_a_low_confidence_field_improves_only_the_merged_score():
    # The parser left batch_no blank and flagged it; the LLM's grounded, well-formed value fixes
    # it. Baseline must still show the parser's own miss - that is the whole point of the gates.
    example = _example(
        text="Batch No: TB-1201 Mfg 09/2024",
        fields={**dict.fromkeys(B_FIELDS, ""), "batch_no": "TB-1201"},
        parser_fields=dict.fromkeys(B_FIELDS, ""),
        low_confidence_fields=["batch_no"],
        confidence="low",
    )
    baseline, merged = ScoreSet(), ScoreSet()
    out = score_one(example, _reply(batch_no="TB-1201"), baseline, merged)
    assert baseline.overall.fn == 1  # the parser's own blank: a miss
    assert merged.overall.tp == 1 and merged.overall.fn == 0  # the LLM's fix: a hit
    assert baseline.low_confidence.fn == 1  # this row counts toward gate 1's subset
    assert merged.low_confidence.tp == 1
    expected = [{"field": "batch_no", "value": "TB-1201", "text": example["text"]}]
    assert out["substitutions"] == expected


def test_an_ungrounded_llm_value_cannot_make_the_merged_score_worse_than_a_blank_miss():
    # The parser is blank (a miss either way); the LLM invents something never printed. merge()
    # rejects it on grounding, so the merged score is UNCHANGED from baseline - not turned into a
    # wrong-value penalty by a value that was never going to be accepted.
    example = _example(
        text="Batch No: TB-1201 Mfg 09/2024",
        fields={**dict.fromkeys(B_FIELDS, ""), "batch_no": "TB-1201"},
        parser_fields=dict.fromkeys(B_FIELDS, ""),
        low_confidence_fields=["batch_no"],
        confidence="low",
    )
    baseline, merged = ScoreSet(), ScoreSet()
    out = score_one(example, _reply(batch_no="TB-9999"), baseline, merged)
    assert baseline.overall.fn == 1
    assert merged.overall.fn == 1  # still a miss - the invented value was never accepted
    assert out["substitutions"] == []  # nothing actually changed: merge() kept the parser's blank


def test_a_grounded_but_partial_value_on_a_multi_part_row_can_cost_an_extra_false_positive():
    # The real shape of the one genuine parser error in the test split (PROGRESS.md step 4): a
    # two-part pack whose LABEL joins both printed batch numbers with " | ", which is not how
    # they appear contiguously on the page. An LLM reply naming only ONE of the two IS grounded
    # (it really is printed) and well-formed, so merge() accepts it - but it does not equal the
    # compound label under exact-match scoring, so this turns a clean miss (FN) into a wrong
    # answer (FP+FN): the honest reason gate 1 is not a given, even though grounding did its job.
    example = _example(
        text="S.No Batch 2. 911805 WB7L20 Mfg 03/2018 12/2017",
        fields={**dict.fromkeys(B_FIELDS, ""), "batch_no": "911805 | WB7L20"},
        parser_fields=dict.fromkeys(B_FIELDS, ""),
        low_confidence_fields=["batch_no"],
        confidence="low",
    )
    baseline, merged = ScoreSet(), ScoreSet()
    score_one(example, _reply(batch_no="911805"), baseline, merged)
    assert baseline.overall.fn == 1 and baseline.overall.fp == 0
    assert merged.overall.fp == 1 and merged.overall.fn == 1  # worse, not better, on this field


def test_schema_exact_is_false_for_unusable_json():
    example = _example()
    baseline, merged = ScoreSet(), ScoreSet()
    out = score_one(example, "not json at all", baseline, merged)
    assert out["schema_exact"] is False
    assert out["substitutions"] == []  # merge() falls back to the parser's values entirely


# ------------------------------------------------------------------ the real written file, if any


def test_no_leaked_pdf_or_family_in_the_real_test_file():
    """Mirrors `test_training_data.test_no_leaked_pdf_in_the_real_training_file`: skipped unless
    a real run has actually written the file, and then checks it for real."""
    test_file = Path("../data/llm-training/test.jsonl")
    manifest_file = Path("../extraction/eval/manifest.csv")
    if not test_file.exists() or not manifest_file.exists():
        pytest.skip("no real test file on this machine yet (run evaluate.py)")

    import csv

    with manifest_file.open(newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))
    test_shas = {r["source_sha256"] for r in manifest if r["split"] == "test"}

    with test_file.open(encoding="utf-8") as f:
        examples = [json.loads(line) for line in f if line.strip()]
    assert examples, "the test file is empty"
    assert "E" not in {e["family"] for e in examples}
    for example in examples:
        sha = example["source_key"].rsplit("/", 1)[-1].removesuffix(".pdf")
        assert sha in test_shas, f"{example['source_key']} is not a test-split PDF"
