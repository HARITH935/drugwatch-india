"""Phase 10 step 3: the gate every LLM-filled value must pass before the pipeline accepts it.

Three per-field checks, matching decision D4 (PROGRESS.md, Phase 10):

1. SCHEMA - exactly the right fields for this family, nothing extra, nothing missing. Already
   built in `prompting.parse_reply`; a reply that fails this cannot be trusted field by field.
2. GROUNDING - a value must appear in the row's own source text (`prompting.grounded`). This is
   what makes a hallucinated value catchable: an invented date cannot be grounded in text that
   never printed it.
3. PLAUSIBILITY - a non-blank value must be well-formed for its field - reusing
   `confidence.field_problem`, the SAME shape check Phase 2 already runs on the rule parser's own
   output. The LLM is held to the identical bar, not a looser one. This is CLAUDE.md §5's
   "impossible dates or invented fields are rejected", applied to the LLM specifically.

Plus one ROW-level guard, added after step 5's single-use test: a MULTI-PART PACK
(`family_d.MULTI_PART_PACK_WARNING`) is never offered to the LLM at all. Step 5 measured why -
the only genuine parser mistake in the whole test split was exactly this shape, and the result
was a real regression (gate 1 92.3% -> 85.7%, gate 2 99.5% -> 99.0%), not merely a non-improvement.
The row's own LABEL joins two real, printed values with " | ", so a value the LLM names passes
grounding and plausibility (it really is printed, it really is well-formed) while still being
WRONG under exact-match scoring, because half of a compound answer is not the compound answer.
Grounding exists to catch invention; it has no way to catch "a real but partial answer to a
question with a compound answer" - so this is caught by name instead, for the one shape measured
to cause it, rather than loosened to let more rows through on a guess.

`merge()` is D4 itself plus this guard: the fallback may only replace a field the parser flagged
low-confidence, only with a value that survives all three per-field checks, and never on a row
the parser itself could not split. Every other field keeps the parser's value even when the LLM
disagrees with it - a missed correction is accepted; a wrong one is not.
"""

from collections.abc import Sequence

from drugwatch_extraction.confidence import field_problem
from drugwatch_extraction.family_d import MULTI_PART_PACK_WARNING
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


def is_unsplittable_multi_part(warnings: Sequence[str]) -> bool:
    """True for exactly the row shape step 5 measured to make the fallback worse, not just
    unhelpful: a label printed twice in one cell (two batches, one row), which `family_d` already
    refuses to guess apart. Its own LABEL joins both real values with " | ", so nothing the LLM
    can ground-truth-check against the row's text will ever equal that compound answer."""
    return MULTI_PART_PACK_WARNING in warnings


def merge(
    parser_fields: dict[str, str],
    raw_reply: str,
    family: str,
    source_text: str,
    low_confidence_fields: set[str],
    warnings: Sequence[str] = (),
) -> dict[str, str]:
    """The final fields: the parser's own value for every field, EXCEPT a low-confidence field
    where the LLM's value passed every check - decision D4, not a looser merge. `warnings`
    defaults to empty for callers (and tests) that predate the multi-part-pack guard; a caller
    that never passes a row's real warnings simply never trips it, which is the safe default -
    the guard can only ever REFUSE a correction, never grant one it wouldn't otherwise have."""
    if is_unsplittable_multi_part(warnings):
        return dict(parser_fields)
    parsed = parse_reply(raw_reply, family)
    accepted = accepted_fields(raw_reply, family, source_text)
    result = dict(parser_fields)
    for field in expected_fields(family):
        if field in low_confidence_fields and accepted.get(field):
            result[field] = parsed[field]
    return result
