"""A confidence flag per record (Phase 2 step 5: "required fields present and well-formed = high").

    assess(record) -> ("high" | "low", reasons)

HIGH: every REQUIRED field holds a value of the right shape, and the parser raised no warning for
the row. LOW: anything else, with every reason listed as "<field>: <problem>", so later steps can
pick the low rows that matter to them. Phase 10's LLM fallback can only help where the parser
misread the PDF ("parser warning"), not where the PDF itself prints "NIL" or an Excel day number.

The checks read a COMPACT copy of each value (spaces and line breaks removed, lower case, trailing
"." "," ";" dropped), so "0 9 / 2 0 2 4 ." and "Dec/202\\n3" are dates. The record itself is never
changed: bronze keeps values as extracted (rows.py).
"""

import re
from typing import Any

SHARED = ("product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer")
# Family F (the Apr 2024 spurious list) has no failure column: its finding is that the pack is fake.
REQUIRED = {family: (*SHARED, "failure_reason") for family in "ABCDE"} | {"F": SHARED}
DATE_FIELDS = ("mfg_date", "expiry_date")

# Printed in place of a value: the PDF itself says there is none (compact form).
NOT_STATED = {"-", "--", "nil", "na", "n/a", "nm", "notmentioned", "noexpiry"}

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")  # fmt: skip
_SEP = r"[-/.',]+"  # "03/2025", "Mar-2025", "22.01.2024", "Feb'16", "June, 2023", "Apr--2026"
_DATE = re.compile(
    rf"(?:(?P<day>\d{{1,2}}){_SEP})?(?P<month>\d{{1,2}}|[a-z]{{3,9}}){_SEP}(?P<year>\d{{4}}|\d{{2}})"
)
# A spreadsheet date exported as its number: days since 1899-12-30. 32874..54788 = 1990..2049.
_EXCEL_DAY = re.compile(r"\d{5}")
_EXCEL_RANGE = range(32874, 54789)


def assess(record: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = []
    for field in REQUIRED.get(record.get("family"), SHARED):
        problem = field_problem(field, record.get(field))
        if problem:
            reasons.append(f"{field}: {problem}")
    if record.get("warnings"):
        reasons.append("parser warning")  # the messages themselves stay in record["warnings"]
    return ("low" if reasons else "high"), reasons


def field_problem(field: str, value: str | None) -> str | None:
    """What's wrong with one field's value, or None when it is well-formed."""
    if value is None or not value.strip():
        return "missing"
    compact = re.sub(r"\s+", "", value).lower().rstrip(".,;")
    # A vaccine list's "Manufactured By" can say "Spurious": the real maker is unknown.
    if compact in NOT_STATED or (field == "manufacturer" and compact == "spurious"):
        return "not stated"
    if field in DATE_FIELDS:
        if _is_date(compact):
            return None
        if _EXCEL_DAY.fullmatch(compact) and int(compact) in _EXCEL_RANGE:
            return "Excel day number"
        return "not a date"  # e.g. "3 Yrs from the date of Mfg." or two dates in one cell
    if field == "batch_no":
        if not re.search(r"\d", compact):
            return "no digit"
        if re.search(r"[,;&]", compact):
            return "several values"  # two batches in one cell: which one failed?
    if field in ("product_name", "manufacturer") and not re.search(r"[a-z]{3}", compact):
        return "no name"
    return None


def _is_date(compact: str) -> bool:
    match = _DATE.fullmatch(compact)
    if match is None:
        return False
    day, month, year = match["day"], match["month"], match["year"]
    if month.isdigit():
        month_ok = 1 <= int(month) <= 12
    else:
        month_ok = any(name.startswith(month) for name in _MONTHS)  # "mar", "june", "sept"
    day_ok = day is None or 1 <= int(day) <= 31
    year_ok = len(year) == 2 or 1990 <= int(year) <= 2049
    return month_ok and day_ok and year_ok
