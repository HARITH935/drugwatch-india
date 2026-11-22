"""Phase 10 step 3's adversarial tests: the specific failure modes D4 exists to catch.

No real CDSCO text (ADR 0003): every row here is made up, chosen to exercise one failure mode at
a time.
"""

from drugwatch_llm.validator import accepted_fields, merge, plausible

B_FIELDS = ("product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer", "failure_reason")


def _reply(**fields) -> str:
    base = dict.fromkeys(B_FIELDS, "")
    base.update(fields)
    import json

    return json.dumps(base)


# ------------------------------------------------------------------ the adversarial cases


def test_nil_can_never_become_a_fabricated_date():
    # The exact failure mode CLAUDE.md §5 names: "impossible dates or invented fields are
    # rejected". The source cell says NIL; the model invents a plausible-looking date anyway.
    source = "S.No Batch Mfg Date Expiry Date 11. TB-1201 NIL 08/2026"
    reply = _reply(batch_no="TB-1201", mfg_date="09/2024", expiry_date="08/2026")
    accepted = accepted_fields(reply, "B", source)
    # "09/2024" never appears in the source text: not grounded, however plausible it looks.
    assert accepted["mfg_date"] is False
    # "08/2026" DOES appear and is a real date: correctly accepted.
    assert accepted["expiry_date"] is True


def test_an_extra_invented_field_fails_the_whole_reply():
    reply = (
        '{"product_name": "X", "batch_no": "Y", "mfg_date": "", "expiry_date": "", '
        '"manufacturer": "", "failure_reason": "", "generic_name": "invented"}'
    )
    assert accepted_fields(reply, "B", "X Y anything") == {}


def test_a_grounded_but_malformed_batch_number_is_rejected():
    # The model copies the right-looking words, but they aren't a batch number at all - no
    # digit, so confidence.field_problem (the same check the parser is held to) rejects it.
    source = "Batch No: See Label Mfg 09/2024"
    reply = _reply(batch_no="See Label", mfg_date="09/2024")
    accepted = accepted_fields(reply, "B", source)
    assert accepted["batch_no"] is False  # grounded, but not well-formed
    assert accepted["mfg_date"] is True


def test_a_well_formed_but_ungrounded_value_is_rejected():
    # Plausible on its own, but never printed anywhere in this row: invented, not read.
    source = "Batch No: TB-1201 Mfg 09/2024"
    reply = _reply(batch_no="TB-1201", mfg_date="01/2099")  # a real-shaped date, never in source
    accepted = accepted_fields(reply, "B", source)
    assert accepted["mfg_date"] is False


def test_a_genuinely_blank_value_is_accepted_as_a_real_answer():
    # The cell really is empty - a legitimate, checkable answer, not a hallucination.
    source = "Batch No: TB-1201 Expiry: --"
    reply = _reply(batch_no="TB-1201", expiry_date="")
    accepted = accepted_fields(reply, "B", source)
    assert accepted["expiry_date"] is True


def test_plausible_rejects_an_impossible_date_even_if_it_were_somehow_grounded():
    assert plausible("mfg_date", "45/2024") is False  # no 45th month
    assert plausible("mfg_date", "09/2024") is True
    assert plausible("mfg_date", "") is True  # blank is a real answer


# ------------------------------------------------------------------ merge (D4 itself)


def test_merge_only_touches_fields_the_parser_flagged_low_confidence():
    # product_name's alternative is grounded AND well-formed - the only reason it must be
    # refused is that the parser never flagged that field, isolating D4's real restriction
    # from the grounding/plausibility checks already covered elsewhere.
    source = "Old Name New Name Batch No: TB-1201 Mfg 09/2024"
    parser_fields = {
        "product_name": "Old Name",  # the parser's own value: high-confidence, not flagged
        "batch_no": "TB-1201",
        "mfg_date": "09/2024",
        "expiry_date": "",
        "manufacturer": "",
        "failure_reason": "",
    }
    reply = _reply(product_name="New Name", batch_no="TB-1201", mfg_date="09/2024")
    merged = merge(parser_fields, reply, "B", source, low_confidence_fields={"batch_no"})
    # Only batch_no was flagged, so only batch_no could ever change - product_name stays even
    # though the LLM's alternative would otherwise have passed every check.
    assert merged["product_name"] == "Old Name"
    assert merged["batch_no"] == "TB-1201"


def test_merge_falls_back_to_the_parser_when_the_llm_fails_a_check():
    source = "Batch No: garbled Mfg 09/2024"
    parser_fields = {
        "product_name": "",
        "batch_no": "garbled",  # the parser's own low-confidence value
        "mfg_date": "09/2024",
        "expiry_date": "",
        "manufacturer": "",
        "failure_reason": "",
    }
    reply = _reply(batch_no="TB-9999", mfg_date="09/2024")  # invented: not grounded
    merged = merge(parser_fields, reply, "B", source, low_confidence_fields={"batch_no"})
    # TB-9999 is not in the source text, so the parser's own (also imperfect) value is kept
    # rather than being overwritten with something invented.
    assert merged["batch_no"] == "garbled"


def test_merge_uses_the_llms_value_only_when_flagged_and_everything_passes():
    source = "Batch No: TB-1201-CORRECTED Mfg 09/2024"
    parser_fields = {
        "product_name": "",
        "batch_no": "TB-1201",  # the parser read it short; flagged low-confidence
        "mfg_date": "09/2024",
        "expiry_date": "",
        "manufacturer": "",
        "failure_reason": "",
    }
    reply = _reply(batch_no="TB-1201-CORRECTED", mfg_date="09/2024")
    merged = merge(parser_fields, reply, "B", source, low_confidence_fields={"batch_no"})
    assert merged["batch_no"] == "TB-1201-CORRECTED"


def test_merge_with_an_unparseable_reply_keeps_every_parser_value():
    parser_fields = {
        "product_name": "X",
        "batch_no": "Y",
        "mfg_date": "09/2024",
        "expiry_date": "",
        "manufacturer": "",
        "failure_reason": "",
    }
    merged = merge(
        parser_fields, "not json at all", "B", "anything", low_confidence_fields={"batch_no"}
    )
    assert merged == parser_fields
