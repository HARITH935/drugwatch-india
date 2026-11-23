"""Phase 10 step 4: LoRA fine-tune of Qwen2.5-1.5B-Instruct (chosen in step 2; ADR 0019's
amendment) on the 737 training examples from step 1.

A PLAIN TRAINING LOOP, not `transformers.Trainer`. Measured, not assumed: a raw forward + backward
+ optimizer step on this Mac's MPS backend takes ~0.4s once warmed up; the identical model and
data run through `Trainer` took ~97s PER EXAMPLE - about 250x slower, diagnosed down to the
Trainer/accelerate path itself (not the model, not memory: the smoke run that surfaced this used
only 499 MB peak RSS). A single LoRA run is simple enough that writing the dozen lines Trainer
would otherwise hide is cheaper than chasing an unexplained 250x gap on a platform with less
MPS-specific testing than CUDA gets.

Deliberately NOT talking to MLflow here, for the same reason step 2 separated inference from
Docker: training needs more memory than a forward pass (gradients, an optimizer's state), and
Docker's resident VM competes for the same 8 GB. `publish_run.py` is the separate, lightweight
step that opens MLflow (Docker back up) afterwards, with no model in memory at the time.

Run (from llm/, no .env/Docker needed; wrap in caffeinate -i; quit Docker Desktop first for
anything beyond a tiny smoke run):
    uv run python -m drugwatch_llm.train --limit 10 --epochs 1   # smoke test first - always
    caffeinate -i uv run python -m drugwatch_llm.train            # the real run
"""

import argparse
import gc
import json
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from torch.utils.data import DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer

from drugwatch_llm.dataset import JSONExtractionDataset, collate
from drugwatch_llm.smoke_test import peak_rss_mb
from drugwatch_llm.zero_shot import device_for

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
TRAIN_PATH = Path("../data/llm-training/train.jsonl")  # real CDSCO text: git-ignored (ADR 0003)
RUN_DIR = Path("../data/llm-training/runs")  # adapters + run_info.json: also git-ignored

# A fixed length covers every real training row with margin (step 1's examples are short rows,
# not whole pages) while still giving `JSONExtractionDataset` something concrete to drop an
# oversized row against, rather than silently truncating into the middle of an answer.
MAX_LENGTH = 512

# Attention-only LoRA: the four projection matrices that decide what the model attends to, not
# its MLP layers. Keeps the trainable parameter count - and so the optimizer's memory - small.
LORA_CONFIG = {
    "r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "task_type": "CAUSAL_LM",
}


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_model_and_tokenizer(device: str):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token  # Qwen2.5 has no pad token by default
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16).to(device)
    model = get_peft_model(model, LoraConfig(**LORA_CONFIG))
    model.train()
    return model, tokenizer


def train(
    model,
    loader: DataLoader,
    device: str,
    epochs: float,
    grad_accum: int,
    lr: float,
    log_every: int = 10,
) -> dict:
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    steps_per_epoch = len(loader)
    total_micro_batches = int(steps_per_epoch * epochs)

    losses = []
    micro_batch = 0
    optimizer.zero_grad()
    started = time.monotonic()
    while micro_batch < total_micro_batches:
        for batch in loader:
            if micro_batch >= total_micro_batches:
                break
            batch = {k: v.to(device) for k, v in batch.items()}
            out = model(**batch)
            (out.loss / grad_accum).backward()
            losses.append(out.loss.item())
            micro_batch += 1
            if micro_batch % grad_accum == 0 or micro_batch == total_micro_batches:
                optimizer.step()
                optimizer.zero_grad()
            if micro_batch % log_every == 0:
                recent = losses[-log_every:]
                print(
                    f"  {micro_batch}/{total_micro_batches}  loss={sum(recent) / len(recent):.4f}"
                )
    elapsed = time.monotonic() - started
    return {
        "micro_batches": total_micro_batches,
        "final_loss": sum(losses[-log_every:]) / len(losses[-log_every:]) if losses else None,
        "mean_loss": sum(losses) / len(losses) if losses else None,
        "elapsed_seconds": elapsed,
        "seconds_per_example": elapsed / total_micro_batches if total_micro_batches else 0.0,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="LoRA fine-tune for Phase 10's extraction fallback."
    )
    parser.add_argument("--limit", type=int, default=None, help="train on only the first N rows")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args(argv)

    examples = load_jsonl(TRAIN_PATH)
    if args.limit:
        examples = examples[: args.limit]
    device = device_for()
    print(f"{len(examples)} training examples, device={device}")

    model, tokenizer = build_model_and_tokenizer(device)
    model.print_trainable_parameters()

    dataset = JSONExtractionDataset(examples, tokenizer, max_length=MAX_LENGTH)
    print(f"{len(dataset)} tokenized rows ({dataset.dropped} dropped: over {MAX_LENGTH} tokens)")
    loader = DataLoader(
        dataset,
        batch_size=1,  # one row at a time; grad_accum does the batching over steps instead
        shuffle=True,
        collate_fn=lambda batch: collate(batch, tokenizer.pad_token_id),
    )

    run_name = args.run_name or time.strftime("%Y%m%d-%H%M%S")
    output_dir = RUN_DIR / run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Fine for a real multi-hundred-step run; a tiny smoke run needs finer-grained logging or it
    # prints nothing until the very end - the exact silence that hid the Trainer-overhead problem.
    total_steps = max(1, int(len(dataset) * args.epochs))
    log_every = min(10, max(1, total_steps // 4))
    result = train(model, loader, device, args.epochs, args.grad_accum, args.lr, log_every)

    adapter_dir = output_dir / "adapter"
    model.save_pretrained(str(adapter_dir))  # the LoRA weights only - a few MB, not the base model
    tokenizer.save_pretrained(str(adapter_dir))
    del model
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()

    info = {
        "model_id": MODEL_ID,
        "run_name": run_name,
        "lora_config": LORA_CONFIG,
        "training_args": {
            "epochs": args.epochs,
            "grad_accum": args.grad_accum,
            "lr": args.lr,
        },
        "examples": len(dataset),
        "dropped_examples": dataset.dropped,
        **result,
        "peak_rss_mb": peak_rss_mb(),
        "device": device,
    }
    (output_dir / "run_info.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    print(f"\nAdapter saved to {adapter_dir}")


if __name__ == "__main__":
    main()
