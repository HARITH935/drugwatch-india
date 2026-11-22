from drugwatch_llm.prompting import (
    build_prompt,
    expected_fields,
    grounded,
    parse_any_json,
    parse_reply,
)


def test_family_f_has_no_failure_reason_in_its_field_list():
    # docs/extraction-report.md §2.9: family F's alert has no failure column at all.
    assert "failure_reason" not in expected_fields("F")
    assert "failure_reason" in expected_fields("B")


def test_prompt_names_exactly_the_fields_this_family_has():
    prompt = build_prompt("some row text", "F")
    assert "failure_reason" not in prompt
    assert "product_name" in prompt


def test_a_clean_json_reply_parses():
    raw = '{"product_name": "X", "batch_no": "Y", "mfg_date": "09/2024", "expiry_date": "08/2026", "manufacturer": "Z", "failure_reason": "Assay"}'  # noqa: E501
    parsed = parse_reply(raw, "B")
    assert parsed["batch_no"] == "Y"


def test_a_reply_wrapped_in_markdown_fences_still_parses():
    raw = '```json\n{"product_name": "X", "batch_no": "Y", "mfg_date": "", "expiry_date": "", "manufacturer": "", "failure_reason": ""}\n```'  # noqa: E501
    assert parse_reply(raw, "B") is not None


def test_a_reply_missing_a_field_is_rejected_not_filled_in():
    raw = '{"product_name": "X", "batch_no": "Y"}'
    assert parse_reply(raw, "B") is None


def test_a_reply_with_an_extra_invented_field_is_rejected():
    raw = (
        '{"product_name": "X", "batch_no": "Y", "mfg_date": "", "expiry_date": "", '
        '"manufacturer": "", "failure_reason": "", "generic_name": "Z"}'
    )
    assert parse_reply(raw, "B") is None


def test_not_json_at_all_is_rejected():
    assert parse_reply("I'm sorry, I cannot read this row.", "B") is None


def test_valid_json_with_the_wrong_keys_is_distinguishable_from_no_json_at_all():
    # Two different problems a report should tell apart: "can't produce JSON" vs "produces JSON,
    # wrong fields" - the first is a prompting problem, the second is closer to the right track.
    wrong_schema = '{"name": "X", "lot": "Y"}'
    assert parse_any_json(wrong_schema) is not None
    assert parse_reply(wrong_schema, "B") is None
    assert parse_any_json("not json at all") is None


def test_a_value_present_in_the_source_text_is_grounded():
    assert grounded("TB-1201", "Row text: Paracetamol Batch TB-1201 Mfg 09/2024")


def test_a_blank_value_is_always_grounded():
    assert grounded("", "anything at all")


def test_an_invented_value_not_in_the_source_text_is_not_grounded():
    assert not grounded("TB-9999", "Row text: Paracetamol Batch TB-1201 Mfg 09/2024")


def test_grounding_ignores_whitespace_and_case_like_the_eval_sets_own_comparison():
    # docs/eval-set.md §4: spaces and line breaks don't count. Punctuation does - a hyphen the
    # model drops is a real difference, not noise, so this only tests whitespace and case.
    assert grounded("tb1201", "Batch: TB\n1201")
