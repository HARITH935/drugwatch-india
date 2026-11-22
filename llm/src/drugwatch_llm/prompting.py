"""The prompt given to every candidate model, and how its reply is turned back into fields.

One prompt format, shared by step 2's zero-shot comparison and step 4's fine-tuning: a model
trained on one prompt shape and evaluated on another would not really be the model being tested.

The field list is INSTRUCTION, not something the model has to guess: family F's alert has no
failure column at all (docs/extraction-report.md §2.9), so asking a model to invent one there
would be scoring it on a question that has no right answer. `confidence.REQUIRED` is the same
per-family field list the parser itself is held to (`confidence.py`, `evaluate.py`) - reusing it
means the model is judged by the same yardstick as the row-based engine it is a fallback for.
"""

import json
import re
from typing import Any

from drugwatch_extraction.confidence import REQUIRED, SHARED

INSTRUCTIONS = """You are reading one row of an Indian drug-regulator alert table. The text below \
is every word from the table's header, then every word of one row, exactly as printed on the \
page - the words are in reading order but NOT aligned to columns, so you must work out which \
field each word belongs to from its meaning, not its position on the line.

Reply with ONLY a JSON object, no other text, with exactly these fields: {fields}
- Copy each value EXACTLY as printed: same spelling, case and punctuation. Do not translate, \
correct, complete or reformat a date.
- If a field's cell is empty, use "".
- Use only words that appear in the text below. Never invent a value."""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def expected_fields(family: str) -> tuple[str, ...]:
    return REQUIRED.get(family, SHARED)


def build_prompt(text: str, family: str) -> str:
    fields = expected_fields(family)
    return f"{INSTRUCTIONS.format(fields=', '.join(fields))}\n\nText:\n{text}\n\nJSON:"


def parse_any_json(raw: str) -> dict[str, Any] | None:
    """The first JSON object in the reply, with no opinion about which keys it has. Separate from
    `parse_reply` so the zero-shot report can tell "can't produce JSON at all" apart from "produces
    JSON with the wrong fields" - two different problems with two different fixes."""
    match = _JSON_BLOCK.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_reply(raw: str, family: str) -> dict[str, str] | None:
    """The model's reply as a fields dict, or None if it isn't usable: not valid JSON, not an
    object, or missing/extra keys. A model graded on "close enough" JSON would be graded on a
    leniency this phase's real pipeline (step 6) will never extend to it."""
    parsed = parse_any_json(raw)
    if parsed is None:
        return None
    expected = set(expected_fields(family))
    if set(parsed) != expected:
        return None
    if not all(isinstance(v, str) for v in parsed.values()):
        return None
    return parsed


def grounded(value: str, source_text: str) -> bool:
    """True if `value` (collapsed to its words) is a substring of the source text's own words -
    the same check step 3's validator will run for real, built once here so the zero-shot report
    already says how often each candidate invents something outside the row it was given."""
    if value == "":
        return True
    compact = re.sub(r"\s+", "", value.lower())
    source = re.sub(r"\s+", "", source_text.lower())
    return compact in source
