"""Phase 10 step 2: compare candidate models, zero-shot, on the validation split.

Before any fine-tuning happens, this asks the cheapest possible question: can an off-the-shelf
instruction-tuned model do any of this job at all? If none of them can produce the right JSON
shape zero-shot, that is worth knowing before spending a training run on one. Scored on the
VALIDATION split only - the test split stays untouched for step 5 (CLAUDE.md §5).

Candidates (all Apache-2.0, each confirmed on its own Hugging Face page, 2026-11-22):
- Qwen/Qwen2.5-0.5B-Instruct    - the model step 0 already proved loads and runs.
- Qwen/Qwen2.5-1.5B-Instruct    - same family, 3x the parameters; above ADR 0019's 0.5-1B
  production cap, tried anyway to see whether the extra size is worth revisiting that cap for.
- HuggingFaceTB/SmolLM2-360M-Instruct - a different family, smaller again, the cheap end.

Run (from llm/, needs ../data/llm-training/validation.jsonl - build it first with
validation_data.py; downloads two more models the first time):
    uv run python -m drugwatch_llm.zero_shot
"""

import argparse
import gc
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from drugwatch_extraction.evaluate import Counts, outcome
from drugwatch_llm.prompting import (
    build_prompt,
    expected_fields,
    grounded,
    parse_any_json,
    parse_reply,
)
from drugwatch_llm.smoke_test import peak_rss_mb

VALIDATION_PATH = Path("../data/llm-training/validation.jsonl")
MAX_NEW_TOKENS = 220  # enough for a long manufacturer address plus a wrapped product name

CANDIDATES = (
    "Qwen/Qwen2.5-0.5B-Instruct",
    "Qwen/Qwen2.5-1.5B-Instruct",
    "HuggingFaceTB/SmolLM2-360M-Instruct",
)


@dataclass
class ModelReport:
    model_id: str
    rows: int
    json_valid: int  # produced SOME parseable JSON object, right fields or not
    schema_exact: int  # produced exactly the right fields (implies json_valid)
    grounded_values: int
    non_blank_values: int
    overall: Counts = field(default_factory=Counts)
    by_field: dict[str, Counts] = field(default_factory=dict)
    seconds_per_row: float = 0.0
    peak_rss_mb: float = 0.0

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "rows": self.rows,
            "json_valid_rate": self.json_valid / self.rows if self.rows else 0.0,
            "schema_exact_rate": self.schema_exact / self.rows if self.rows else 0.0,
            "grounded_rate": self.grounded_values / self.non_blank_values
            if self.non_blank_values
            else 0.0,
            "overall_f1": self.overall.f1,
            "by_field_f1": {field: counts.f1 for field, counts in self.by_field.items()},
            "seconds_per_row": self.seconds_per_row,
            "peak_rss_mb": self.peak_rss_mb,
        }


def load_examples(path: Path = VALIDATION_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def device_for(torch_module=torch) -> str:
    return "mps" if torch_module.backends.mps.is_available() else "cpu"


def generate(model, tokenizer, prompt: str, device: str) -> str:
    messages = [{"role": "user", "content": prompt}]
    # transformers 5.x: with return_tensors set, this returns a BatchEncoding (input_ids +
    # attention_mask), not a bare tensor - passing it straight to generate() as `input_ids`
    # fails with a confusing AttributeError deep inside generate(), not here.
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    ).to(device)
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,  # greedy: a fair, reproducible comparison across candidates
            pad_token_id=tokenizer.eos_token_id,
        )
    prompt_length = inputs["input_ids"].shape[1]
    return tokenizer.decode(output[0][prompt_length:], skip_special_tokens=True)


def run_model(model_id: str, examples: list[dict], device: str) -> ModelReport:
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    # bfloat16, not float32: float32 cost this script a 30-minute stall the first time it ran -
    # the 1.5B candidate alone needs ~6 GB of weights at 4 bytes/param, on top of whatever else
    # is resident (Docker Desktop's VM reserves ~4.8 GB on this Mac on its own). Halving it to 2
    # bytes/param is the difference between fitting and swapping. Inference-only, so the lower
    # precision costs nothing this phase will ever train against.
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16).to(device)
    model.eval()

    report = ModelReport(model_id=model_id, rows=len(examples), json_valid=0, schema_exact=0,
                          grounded_values=0, non_blank_values=0)  # fmt: skip
    started = time.monotonic()
    for index, example in enumerate(examples, start=1):
        family = example["family"]
        reply = generate(model, tokenizer, build_prompt(example["text"], family), device)
        if parse_any_json(reply) is not None:
            report.json_valid += 1
        parsed = parse_reply(reply, family)
        if parsed is not None:
            report.schema_exact += 1
        for name in expected_fields(family):
            got = (parsed or {}).get(name)
            label = example["fields"].get(name, "")
            result = outcome(label, got)
            if result:
                report.overall.add(result)
                report.by_field.setdefault(name, Counts()).add(result)
            if got:
                report.non_blank_values += 1
                report.grounded_values += int(grounded(got, example["text"]))
        # A silent multi-minute script hid the float32 memory stall last time. `end="\r"` would
        # repeat that mistake in a different way: it looks fine at a live terminal but is
        # invisible to anything reading the redirected log a line at a time (tail -f, a monitor),
        # which is exactly how a background run like this one gets watched. A real newline, every
        # 5th row, is visible either way and isn't spammy.
        if index % 5 == 0 or index == len(examples):
            print(f"  {model_id}: row {index}/{len(examples)}", file=sys.stderr)
    report.seconds_per_row = (time.monotonic() - started) / len(examples) if examples else 0.0
    report.peak_rss_mb = peak_rss_mb()

    del model, tokenizer
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()  # MPS caches allocations even after Python frees the tensors
    return report


def print_report(report: ModelReport) -> None:
    d = report.to_dict()
    print(f"\n{d['model_id']}")
    print(f"  rows scored:        {report.rows}")
    print(f"  JSON at all:        {d['json_valid_rate']:.1%}")
    print(f"  right schema:       {d['schema_exact_rate']:.1%}")
    print(f"  grounded values:    {d['grounded_rate']:.1%}  (non-blank values only)")
    print(f"  overall field F1:   {d['overall_f1']:.1%}")
    for name, f1 in sorted(d["by_field_f1"].items()):
        print(f"    {name:16} {f1:.1%}")
    print(f"  time/row:           {d['seconds_per_row']:.2f}s")
    print(f"  peak RSS so far:    {d['peak_rss_mb']:.0f} MB")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Zero-shot model comparison on validation.")
    parser.add_argument("--models", nargs="+", default=list(CANDIDATES))
    parser.add_argument("--limit", type=int, default=None, help="score only the first N rows")
    args = parser.parse_args(argv)

    examples = load_examples()
    if args.limit:
        examples = examples[: args.limit]
    device = device_for()
    print(f"{len(examples)} validation rows, device={device}")

    reports = [run_model(model_id, examples, device) for model_id in args.models]
    for report in reports:
        print_report(report)

    best = max(reports, key=lambda r: r.overall.f1)
    print(f"\nHighest overall F1: {best.model_id} ({best.overall.f1:.1%})")


if __name__ == "__main__":
    main()
