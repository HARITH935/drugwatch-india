"""`fallback.py`'s own decision logic: no real CDSCO text (ADR 0003), no real model, no real
bronze - made-up records and made-up replies, the same way `test_evaluate.py` and
`test_validator.py` exercise `merge`/`score_one` without either. The real PDF-reading and
real-model halves are exercised by actually running `fallback.py --dry-run` and
`fallback.py --all` against the stack, not here.
"""

import json

from drugwatch_llm.fallback import apply_merge_to_row, is_candidate

B_FIELDS = ("product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer", "failure_reason")


def _reply(**fields) -> str:
    base = dict.fromkeys(B_FIELDS, "")
    base.update(fields)
    return json.dumps(base)


def _record(**overrides) -> dict:
    base = {
        "family": "B",
        "product_name": "Zyntophil",
        "batch_no": "",
        "mfg_date": "09/2024",
        "expiry_date": "08/2026",
        "manufacturer": "Marvex Labs",
        "failure_reason": "Assay",
        "confidence": "low",
        "warnings": [],
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ is_candidate


def test_a_high_confidence_row_is_never_a_candidate():
    assert is_candidate(_record(confidence="high", batch_no="TB-1201")) is False


def test_an_ordinary_low_confidence_row_is_a_candidate():
    assert is_candidate(_record()) is True


def test_a_multi_part_pack_is_never_a_candidate_even_though_its_low_confidence():
    record = _record(warnings=["a label appears twice (a multi-part pack): not split"])
    assert is_candidate(record) is False


# ------------------------------------------------------------------ apply_merge_to_row


def test_a_real_fix_is_marked_llm_and_reassessed():
    record = _record()  # batch_no blank, everything else well-formed
    changed = apply_merge_to_row(record, _reply(batch_no="TB-1201"), "Batch No: TB-1201")
    assert changed is True
    assert record["batch_no"] == "TB-1201"
    assert record["extraction_method"] == "llm"
    # Every other field was already well-formed, and the fix supplies the one that wasn't -
    # re-running assess() on the now-complete row should find nothing left to flag.
    assert record["confidence"] == "high"


def test_an_llm_reply_the_merge_rejects_changes_nothing_and_is_not_marked():
    record = _record()  # batch_no blank; nothing in the source to ground a value against
    original = dict(record)
    changed = apply_merge_to_row(record, _reply(batch_no="TB-9999"), "no batch number printed here")
    assert changed is False
    assert "extraction_method" not in record  # untouched: the caller's own value, if any, stands
    assert record == original


def test_a_multi_part_pack_passed_in_directly_also_changes_nothing():
    # Belt and suspenders: even if something upstream failed to filter it with is_candidate,
    # merge()'s own row-level guard still refuses every field on this shape.
    record = _record(
        batch_no="", mfg_date="", expiry_date="", manufacturer="",
        warnings=["a label appears twice (a multi-part pack): not split"],
    )  # fmt: skip
    changed = apply_merge_to_row(
        record, _reply(batch_no="911805"), "S.No 2. 911805 WB7L20 03/2018 12/2017"
    )
    assert changed is False
    assert record["batch_no"] == ""


def test_an_unparseable_reply_changes_nothing():
    record = _record()
    changed = apply_merge_to_row(record, "not json at all", "Batch No: TB-1201")
    assert changed is False
