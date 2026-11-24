"""Phase 10 step 5: the single-use test (CLAUDE.md §5 - the test split is never used for training
or tuning, so this reads it exactly once, against the adapter step 4 already trained and
published, and reports the result as-is, whichever way it comes out).

Two gates, decision D3 (PROGRESS.md, Phase 10):

GATE 1 (the plan's own done-when): on the test split's LOW-CONFIDENCE, labelled rows, does
merging in the LLM's (validated) answer score a higher field F1 than the parser alone? The honest
denominator is 6 rows, not the plan's assumed 9 - step 2 already checked the three extra
low-confidence test-split rows outside the sample and found they are all "missing"/"not stated"
(the PDF prints nothing), not parser mistakes, and declined to add them (PROGRESS.md step 1).

GATE 2 (added this phase - the one that actually protects the data): across the WHOLE test split
(69 rows), does the merged result ever score BELOW the parser's own baseline, and does every
accepted LLM value actually appear in its row's own source text? The second half is close to
structurally guaranteed by `validator.merge()` already (grounding is one of its three checks);
this script verifies it directly on every real accepted value rather than trusting that by
construction.

Reuses, rather than rebuilds: `drugwatch_extraction.evaluate`'s `outcome`/`Counts` (the same
scoring the parser's own baseline is measured with) and `zero_shot.generate` (the same generation
code step 2's zero-shot comparison used).

Run (from llm/, RustFS up, the labelled eval set present, a published adapter in
../data/llm-training/runs/<run>/adapter):
    uv run --env-file ../.env python -m drugwatch_llm.evaluate --run kaggle-20261124-043743
"""

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

import pdfplumber
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from drugwatch_extraction.confidence import REQUIRED, field_problem
from drugwatch_extraction.eval_set import bronze_files, load_labels, read_manifest, row_id
from drugwatch_extraction.evaluate import Counts, outcome, table
from drugwatch_ingestion.store import RawStore
from drugwatch_llm.prompting import build_prompt, grounded, parse_reply
from drugwatch_llm.train import MODEL_ID, RUN_DIR
from drugwatch_llm.training_data import row_text
from drugwatch_llm.validator import merge
from drugwatch_llm.zero_shot import device_for, generate

TEST_PATH = Path("../data/llm-training/test.jsonl")  # real CDSCO text: git-ignored (ADR 0003)
REPORT_PATH = Path("../docs/llm-extraction-report.md")

EXCLUDED_FAMILY = "E"  # never in validation/test at all (docs/eval-set.md); checked, not assumed

FIELD_ORDER = (
    "product_name", "batch_no", "mfg_date", "expiry_date", "manufacturer", "failure_reason",
)  # fmt: skip


def low_confidence_fields(record: dict[str, Any]) -> list[str]:
    """Which of this record's own fields the parser itself would flag - the same per-field check
    `confidence.assess` runs, applied field by field so `validator.merge` has exactly what D4
    asks for: a field the parser flagged, not a row the parser flagged."""
    family = record["family"]
    return sorted(
        f for f in REQUIRED.get(family, ()) if field_problem(f, record.get(f)) is not None
    )


def build_test_examples(manifest: list[dict], labels: dict, s3: Any) -> list[dict[str, Any]]:
    """One example per labelled test-split row the parser actually produced a record for (a row
    it lost entirely has no bronze entry to attach a correction to - step 5's scope, same as
    `validation_data.build_examples`; confirmed separately that the real test split has none)."""
    test_shas = {r["source_sha256"] for r in manifest if r["split"] == "test"}
    examples = []
    for records in bronze_files(s3):
        if not records or records[0]["source_sha256"] not in test_shas:
            continue
        key = records[0]["source_key"]
        pdf_bytes = s3.get_object(Bucket="raw", Key=key)["Body"].read()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
            for record in records:
                label = labels.get(row_id(record))
                if label is None:
                    continue  # not a sampled-and-labelled row: no ground truth to score against
                fields = REQUIRED.get(record["family"], ())
                if any(label["fields"].get(f) is None for f in fields):
                    continue  # an unreadable ("/u") field: no trustworthy ground truth
                serial = (record.get("serial_no") or "").strip().rstrip(".")
                text = row_text(
                    document, record["page"], serial, list(record["pages"]), record["family"]
                )
                examples.append(
                    {
                        "text": text,
                        "family": record["family"],
                        "fields": {f: label["fields"].get(f, "") for f in fields},
                        "parser_fields": {f: record.get(f) or "" for f in fields},
                        "low_confidence_fields": low_confidence_fields(record),
                        "confidence": record["confidence"],
                        "source_key": key,
                        "page": record["page"],
                        "row_index": record["row_index"],
                    }
                )
    return examples


def load_model(run_dir: Path, device: str):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16).to(device)
    # Inference only: the backward-pass MPS cliff that sent training to Colab/Kaggle (ADR 0019)
    # does not apply to a forward pass, which step 0 already measured as fine on this Mac.
    model = PeftModel.from_pretrained(base, str(run_dir / "adapter"))
    model.eval()
    return model, tokenizer


class ScoreSet:
    """One row's worth of bookkeeping, split the two ways the gates need: every test row, and
    just the low-confidence ones (gate 1's subset)."""

    def __init__(self) -> None:
        self.overall = Counts()
        self.low_confidence = Counts()
        self.by_field: dict[str, Counts] = {}

    def add(self, field: str, truth: str, got: str, is_low_confidence_row: bool) -> None:
        result = outcome(truth, got)
        if result is None:
            return
        self.overall.add(result)
        self.by_field.setdefault(field, Counts()).add(result)
        if is_low_confidence_row:
            self.low_confidence.add(result)


def score_one(
    example: dict[str, Any], reply: str, baseline: ScoreSet, merged_scores: ScoreSet
) -> dict[str, Any]:
    """One example's contribution to both ScoreSets, plus whether its reply had the right schema
    and which fields actually changed - factored out of `score` so this arithmetic (merge, then
    score both ways, then check what changed) is testable with a made-up `reply`, no model
    needed, the same way `test_validator.py` exercises `merge` with made-up replies."""
    family, text = example["family"], example["text"]
    low_fields = set(example["low_confidence_fields"])
    merged = merge(example["parser_fields"], reply, family, text, low_fields)
    is_low = example["confidence"] == "low"
    substitutions = []
    for field in REQUIRED.get(family, ()):
        truth = example["fields"][field]
        baseline.add(field, truth, example["parser_fields"][field], is_low)
        merged_scores.add(field, truth, merged[field], is_low)
        if merged[field] != example["parser_fields"][field]:
            substitutions.append({"field": field, "value": merged[field], "text": text})
    return {"schema_exact": parse_reply(reply, family) is not None, "substitutions": substitutions}


def score(examples: list[dict], model, tokenizer, device: str) -> dict[str, Any]:
    baseline = ScoreSet()
    merged_scores = ScoreSet()
    schema_exact = 0
    substitutions = []  # every field the LLM's value actually changed, for the ungrounded check
    for index, example in enumerate(examples, start=1):
        reply = generate(model, tokenizer, build_prompt(example["text"], example["family"]), device)
        one = score_one(example, reply, baseline, merged_scores)
        schema_exact += one["schema_exact"]
        substitutions += one["substitutions"]
        if index % 10 == 0 or index == len(examples):
            print(f"  row {index}/{len(examples)}", file=sys.stderr)

    ungrounded = [s for s in substitutions if not grounded(s["value"], s["text"])]
    return {
        "baseline": baseline,
        "merged": merged_scores,
        "rows": len(examples),
        "schema_exact": schema_exact,
        "substitutions": substitutions,
        "ungrounded_substitutions": ungrounded,  # must be empty - merge() should never allow this
    }


def render_report(result: dict[str, Any], run_name: str, run_info: dict[str, Any]) -> str:
    baseline, merged = result["baseline"], result["merged"]
    gate1_pass = merged.low_confidence.f1 > baseline.low_confidence.f1
    gate2_pass = merged.overall.f1 >= baseline.overall.f1 and not result["ungrounded_substitutions"]
    lines = [
        "# Phase 10 step 5 — the single-use test",
        "",
        f"Adapter `{run_name}` (`{run_info.get('model_id')}`, trained on "
        f"{run_info.get('platform', run_info.get('device', 'unknown'))}, "
        f"{run_info.get('examples')} examples) scored against the test split's "
        f"{result['rows']} labelled rows, read exactly once (CLAUDE.md §5).",
        "",
        "*Not medical advice. Data from CDSCO public alerts.*",
        "",
        "## Gate 1 (the plan's done-when): low-confidence test rows",
        "",
        f"Honest n = {baseline.low_confidence.tp + baseline.low_confidence.fp + baseline.low_confidence.fn} "  # noqa: E501
        "field-value pairs over 6 rows, not the plan's assumed 9 (step 2 checked and declined to "
        "pad this; PROGRESS.md step 1).",
        "",
        table("Parser baseline", {"low-confidence rows": baseline.low_confidence}),
        "",
        table("LLM-merged", {"low-confidence rows": merged.low_confidence}),
        "",
        f"**Gate 1: {'PASS' if gate1_pass else 'FAIL'}** "
        f"({merged.low_confidence.f1:.1%} vs baseline {baseline.low_confidence.f1:.1%}).",
        "",
        "## Gate 2 (this phase's added gate): the whole test split",
        "",
        table("Parser baseline", {"all 69 rows": baseline.overall}),
        "",
        table("LLM-merged", {"all 69 rows": merged.overall}),
        "",
        f"**Gate 2: {'PASS' if gate2_pass else 'FAIL'}** — F1 "
        f"{'did not fall' if merged.overall.f1 >= baseline.overall.f1 else 'FELL'} "
        f"({merged.overall.f1:.1%} vs baseline {baseline.overall.f1:.1%}), and "
        f"{len(result['ungrounded_substitutions'])} of "
        f"{len(result['substitutions'])} accepted substitutions were ungrounded "
        "(must be 0 - `validator.merge` checks grounding before accepting any value).",
        "",
        "## By field, whole test split",
        "",
        table("Parser baseline", baseline.by_field, FIELD_ORDER),
        "",
        table("LLM-merged", merged.by_field, FIELD_ORDER),
        "",
        f"The LLM's reply parsed as exactly the right schema on {result['schema_exact']} of "
        f"{result['rows']} rows ({result['schema_exact'] / result['rows']:.1%}).",
        "",
        f"{len(result['substitutions'])} of {result['rows']} rows had a field the LLM's answer "
        "actually changed (the rest: either nothing was low-confidence, or the LLM's answer "
        "failed grounding/plausibility and the parser's own value was kept).",
        "",
        "## What this does not cover",
        "",
        "- **Metric harshness, carried from step 2**: `manufacturer` and `product_name` are scored "
        "on an exact, whitespace-collapsed match - the same bar the parser is held to - so a "
        "reply that is grounded and almost right still scores zero credit for not being "
        "byte-identical.",
        "- **The held-out-layout experiment** (train with one layout family excluded, test on it) "
        "was approved as reported-but-non-gating and is not run here; it needs a second training "
        "run and is deferred.",
        "- **A row the parser lost entirely** is out of this step's scope (and this run) - "
        "the test split has none.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 10 step 5: score the adapter on test.")
    parser.add_argument("--run", required=True, help="run name under ../data/llm-training/runs/")
    parser.add_argument("--limit", type=int, default=None, help="score only the first N rows")
    parser.add_argument("--out", type=Path, default=TEST_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    run_dir = RUN_DIR / args.run
    run_info = json.loads((run_dir / "run_info.json").read_text())

    manifest = read_manifest(Path("../extraction/eval/manifest.csv"))
    labels = load_labels()
    s3 = RawStore.from_env().s3

    examples = build_test_examples(manifest, labels, s3)
    bad_family = {e["family"] for e in examples} & {EXCLUDED_FAMILY}
    if bad_family:
        raise RuntimeError("family E should never appear in validation/test (docs/eval-set.md)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
    print(f"{len(examples)} test examples -> {args.out}")

    if args.limit:
        examples = examples[: args.limit]

    device = device_for()
    print(f"loading {run_info['model_id']} + adapter {args.run}, device={device}")
    model, tokenizer = load_model(run_dir, device)

    result = score(examples, model, tokenizer, device)

    report = render_report(result, args.run, run_info)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    print(f"\nreport -> {args.report}")
    print(report)


if __name__ == "__main__":
    main()
