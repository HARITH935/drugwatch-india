"""Prove the Phase 10 foundations work, before any fine-tuning is built on them.

Four things have to be true:

1. PyTorch can see Apple Silicon's GPU (the "MPS" backend) - without it, training runs on the
   CPU and is much slower.
2. A real candidate model (small, Apache-2.0) downloads and loads from Hugging Face, and can
   run one generation.
3. PEFT can wrap that model with a LoRA adapter - the small, trainable add-on this phase will
   actually fine-tune, instead of all of the base model's weights.
4. The memory cost of loading the model is measured directly (this process's own peak RSS),
   not guessed from how much the whole Mac appears to have free - stopping Docker's containers
   does not release the memory Docker Desktop's VM reserves; only quitting the app does, and this
   project's own training runs will say exactly which one to do.

Run from llm/, no .env needed (nothing here touches RustFS or Postgres):
    uv run python -m drugwatch_llm.smoke_test
"""

import platform
import resource

CANDIDATE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"  # Apache-2.0; confirmed on its Hugging Face page

# ru_maxrss's unit depends on the OS, not the value, so it must be read from the platform, not
# guessed from a magnitude threshold (a 500M-parameter model's RSS and a unit mix-up both land
# in the same range, which is exactly how the first version of this got it wrong silently).
_BYTES_PER_UNIT = 1 if platform.system() == "Darwin" else 1024


def peak_rss_mb() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw * _BYTES_PER_UNIT / (1024 * 1024)


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'ok  ' if ok else 'FAIL'}  {label:52s} {detail}")
    return ok


def main() -> int:
    results = []

    import torch

    mps_available = torch.backends.mps.is_available()
    results.append(
        check(
            "PyTorch sees Apple Silicon's GPU (MPS)",
            mps_available,
            f"torch {torch.__version__}",
        )
    )
    device = "mps" if mps_available else "cpu"

    before_mb = peak_rss_mb()

    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(CANDIDATE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(CANDIDATE_MODEL, dtype=torch.float32)
    model.to(device)
    after_load_mb = peak_rss_mb()
    results.append(
        check(
            f"{CANDIDATE_MODEL} loads",
            True,
            f"{sum(p.numel() for p in model.parameters()):,} parameters,"
            f" +{after_load_mb - before_mb:.0f} MB this process' peak RSS",
        )
    )

    prompt = (
        "Row text: Paracetamol 500mg, Batch: TB-1201, Mfg: 09/2024, Exp: 08/2026. Extract batch_no:"
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    output = model.generate(**inputs, max_new_tokens=10, do_sample=False)
    generated = tokenizer.decode(
        output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
    )
    results.append(
        check(
            "the model generates text from a prompt",
            len(generated.strip()) > 0,
            f"-> {generated.strip()!r}",
        )
    )

    from peft import LoraConfig, get_peft_model

    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        task_type="CAUSAL_LM",
    )
    peft_model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in peft_model.parameters())
    results.append(
        check(
            "PEFT wraps the model with a LoRA adapter",
            0 < trainable < total,
            f"{trainable:,} trainable of {total:,} total ({100 * trainable / total:.2f}%)",
        )
    )

    peak_mb = peak_rss_mb()
    print(f"\nThis process' peak memory: {peak_mb:.0f} MB")

    print()
    if all(results):
        print("Phase 10 foundations are ready")
        return 0
    print("something above is not ready - fix it before building on it")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
