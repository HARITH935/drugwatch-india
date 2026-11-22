"""Phase 10 step 3: the gate every LLM-filled value must pass before the pipeline accepts it.

Three checks, matching decision D4 (PROGRESS.md, Phase 10):

1. SCHEMA - exactly the right fields for this family, nothing extra, nothing missing. Already
   built in `prompting.parse_reply`; a reply that fails this cannot be trusted field by field.
2. GROUNDING - a value must appear in the row's own source text (`prompting.grounded`). This is
   what makes a hallucinated value catchable: an invented date cannot be grounded in text that
   never printed it.
3. PLAUSIBILITY - a non-blank value must be well-formed for its field - reusing
   `confidence.field_problem`, the SAME shape check Phase 2 already runs on the rule parser's own
   output. The LLM is held to the identical bar, not a looser one. This is CLAUDE.md §5's
   "impossible dates or invented fields are rejected", applied to the LLM specifically.

`merge()` is D4 itself: the fallback may only replace a field the parser flagged low-confidence,
and only with a value that survives all three checks. Every other field keeps the parser's value
even when the LLM disagrees with it - a missed correction is accepted; a wrong one is not.
"""

from drugwatch_extraction.confidence import field_problem
from drugwatch_llm.prompting import expected_fields, grounded, parse_reply


def plausible(field: str, value: str) -> bool:
    """A genuinely blank value is plausible - the cell may really be empty, and blank introduces
    no specific wrong fact. A non-blank value must be well-formed for its field."""
    return value == "" or field_problem(field, value) is None


def accepted_fields(raw_reply: str, family: str, source_text: str) -> dict[str, bool]:
    """Which of the model's fields may be trusted, field by field: grounded AND plausible. An
    empty dict means the reply failed the schema check outright - nothing in it can be trusted."""
    parsed = parse_reply(raw_reply, family)
    if parsed is None:
        return {}
    return {
        field: grounded(value, source_text) and plausible(field, value)
        for field, value in parsed.items()
    }


def merge(
    parser_fields: dict[str, str],
    raw_reply: str,
    family: str,
    source_text: str,
    low_confidence_fields: set[str],
) -> dict[str, str]:
    """The final fields: the parser's own value for every field, EXCEPT a low-confidence field
    where the LLM's value passed every check - decision D4, not a looser merge."""
    parsed = parse_reply(raw_reply, family)
    accepted = accepted_fields(raw_reply, family, source_text)
    result = dict(parser_fields)
    for field in expected_fields(family):
        if field in low_confidence_fields and accepted.get(field):
            result[field] = parsed[field]
    return result
