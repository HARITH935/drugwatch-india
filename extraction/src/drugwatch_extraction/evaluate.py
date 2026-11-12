"""Score the rule-based parser against the labelled eval set (Phase 2 step 8).

Every labelled value (one row x one field) is compared with the parser's value in bronze, with all
spaces and line breaks removed (they don't count, docs/eval-set.md §5):

    label has text, parser equal       -> TP  (true positive: right)
    label has text, parser different   -> FP + FN  (a wrong value is invented AND missed)
    label has text, parser empty       -> FN  (missed)
    label blank,    parser has text    -> FP  (invented)
    label blank,    parser blank       -> TN  (right, but not part of precision or recall)
    label unreadable                   -> not scored
    row the parser lost                -> every labelled text value is an FN

    precision = TP / (TP + FP)    recall = TP / (TP + FN)    F1 = 2PR / (P + R)

Scores are reported per field, layout family, split and confidence, and overall (all values pooled,
"micro-averaged"). The test split is reported on its own: it is Phase 10's comparison point.

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.evaluate
"""

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drugwatch_extraction.bronze import bronze_key, read_bronze
from drugwatch_extraction.confidence import SHARED
from drugwatch_extraction.eval_set import LABELS, MANIFEST, load_labels, read_manifest, row_id
from drugwatch_ingestion.store import RawStore

FIELDS = (*SHARED, "failure_reason")


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, outcome: str) -> None:
        for part in outcome.split("+"):  # "FP+FN" counts in both
            setattr(self, part.lower(), getattr(self, part.lower()) + 1)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def _compact(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def outcome(label: str | None, parsed: str | None) -> str | None:
    """TP, FP, FN, FP+FN or TN for one value; None when the label is "can't read it"."""
    if label is None:
        return None
    truth, got = _compact(label), _compact(parsed)
    if not truth:
        return "FP" if got else "TN"
    if not got:
        return "FN"
    return "TP" if got == truth else "FP+FN"


def evaluate(manifest: list[dict], labels: dict, records: dict) -> dict[str, Any]:
    """Counts grouped by field, family, split and confidence, plus every error found."""
    groups: dict[str, dict[str, Counts]] = defaultdict(lambda: defaultdict(Counts))
    errors = []
    for number, item in enumerate(manifest, start=1):
        label = labels.get(row_id(item))
        if label is None:
            continue  # not labelled yet
        record = records.get(row_id(item))  # None: the parser lost this row
        confidence = record["confidence"] if record else "row lost"
        for field, truth in label["fields"].items():
            result = outcome(truth, (record or {}).get(field))
            if result is None:
                continue
            for group, key in (("overall", "all"), ("field", field), ("family", item["family"]),
                               ("split", item["split"]), ("confidence", confidence)):  # fmt: skip
                groups[group][key].add(result)
            if result != "TP" and result != "TN":
                errors.append({"row": number, "field": field, "outcome": result,
                               "family": item["family"], "split": item["split"],
                               "confidence": confidence})  # fmt: skip
    return {"groups": groups, "errors": errors}


def table(name: str, counts: dict[str, Counts], order: tuple = ()) -> str:
    keys = [k for k in order if k in counts] + sorted(k for k in counts if k not in order)
    lines = [
        f"| {name} | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key in keys:
        c = counts[key]
        lines.append(f"| {key} | {c.tp} | {c.fp} | {c.fn} | {c.precision:.1%} | {c.recall:.1%} | "
                     f"{c.f1:.1%} |")  # fmt: skip
    return "\n".join(lines)


def load_records(s3: Any, manifest: list[dict]) -> dict:
    records = {}
    for key in sorted({item["source_key"] for item in manifest}):
        records |= {row_id(r): r for r in read_bronze(s3, bronze_key(key)).to_pylist()}
    return records


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score the parser against the labelled eval set.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args(argv)

    manifest = read_manifest(args.manifest)
    labels = load_labels(args.labels)
    result = evaluate(manifest, labels, load_records(RawStore.from_env().s3, manifest))
    groups = result["groups"]
    labelled = sum(row_id(item) in labels for item in manifest)
    print(f"{labelled} of {len(manifest)} rows labelled\n")
    print(table("Overall", groups["overall"]), end="\n\n")
    print(table("Field", groups["field"], FIELDS), end="\n\n")
    print(table("Family", groups["family"]), end="\n\n")
    print(table("Split", groups["split"], ("train", "validation", "test")), end="\n\n")
    print(table("Confidence", groups["confidence"], ("high", "low")), end="\n\n")
    print(f"{len(result['errors'])} wrong or missing values:")
    for error in result["errors"]:
        where = f"family {error['family']}, {error['split']}, confidence {error['confidence']}"
        print(f"  row {error['row']:3} {error['field']:15} {error['outcome']:6} {where}")


if __name__ == "__main__":
    main()
