# ADR 0019 — The LLM fallback outputs raw printed values; LoRA trains on Colab, not the plan's `YYYY-MM` schema

- **Status:** Accepted (amended 2026-11-22, 2026-11-23 — see below; the training-location half of
  the original decision is reversed by the second amendment)
- **Date:** 2026-11-22
- **Decided by:** Harith (project owner), during Phase 10
- **Affects:** `llm/`, `extraction/` (the Phase 10 fallback integration), `docs/llm-extraction-report.md`

---

## Context

Plan §13 specifies the LLM's output schema, including `mfg_date` and `expiry_date` as `YYYY-MM`,
and lists `generic_name` as a field to extract. It does not say where fine-tuning runs.

**1. Asking for a normalised date invites an invented one.** The archive's PDFs print dates as
`Dec/2023`, `Feb'16`, `30-062025`, Excel day numbers, or placeholders (`NIL`, `Not mentioned`).
Phase 3 already has proven, tested parsers that turn any of these into real dates, keeping the
*source* value alongside the parsed one for provenance (CLAUDE.md §5: "every row keeps
provenance"). If the LLM is asked to output `YYYY-MM` directly, a cell it cannot read confidently
has only two honest outputs — the literal text or nothing — and `YYYY-MM` offers neither; the
easiest wrong answer for a fine-tuned model under that pressure is a plausible-looking guess.
CLAUDE.md §5 is explicit that this must be rejected, not merely discouraged.

**2. `generic_name` cannot be evaluated.** The labelled eval set (`docs/eval-set.md`) has no
`generic_name` label — it was never part of what the rule parser extracts or what the second
reader checked. Training the model to predict a field nothing can score means its only evaluation
is "does it look plausible," which is the one property this phase must not take on faith.

**3. Training location is unconstrained by the plan,** but the model's *production* size is
constrained by where it has to run every month (the local pipeline, later a modest server), which
caps it at roughly 0.5–1B parameters regardless of where fine-tuning happens.

## Options considered

| Option | Trade-off |
|---|---|
| **A. Follow §13 exactly: `YYYY-MM` output, `generic_name` included** | Matches the plan, but trains the model to normalise dates it may misread, and to produce a field with no ground truth. |
| **B. Values as printed, 5 fields (drop `generic_name`), trained locally** | The output can be scored against the labels field-for-field, Phase 3's existing parsers do the normalisation, and training stays on this Mac — no labels leave the laptop (ADR 0003: labels are git-ignored and not published). Cost: a second normalisation pass has to treat LLM output the same as parser output, rather than treating the LLM as already final. |
| **C. Values as printed, trained on Google Colab's free GPU** | Faster fine-tuning, headroom for a bigger model during training. But the production model is capped well below what Colab's GPU would let it try, the labels would be uploaded to a third party, and the work would live partly in a notebook outside the repo rather than as a `uv run` command alongside every other phase. |

## Decision

**Option B.** The fallback outputs `product_name`, `batch_no`, `mfg_date`, `expiry_date`,
`manufacturer`, `failure_reason` — plan §13's 7 fields minus `generic_name` — each exactly as the
source cell prints it, spaces and line breaks collapsed the same way the labelling tool already
does (`docs/eval-set.md` §4). Its output is then run through the **same** date/placeholder/Excel-
day-number normalisation Phase 3 already built and tested, so an LLM-filled field is cleaned
identically to a parser-filled one — one normalisation path, not two.

Fine-tuning runs on this Mac (Apple Silicon, PyTorch's MPS backend), under `caffeinate -i`, with
Docker's services stopped for the duration (measured 4.8 GB of the Mac's 8 GB held by the Docker
VM with everything up; 1.3 GB free on the Mac side). The model is capped in the 0.5–1B range so it
fits both this training setup and the eventual production host.

## Consequences

- Phase 10's evaluation (`docs/llm-extraction-report.md`) scores the LLM's raw text output
  against the labels the same way `evaluate.py` already scores the parser's — one comparison
  method for both extractors.
- The validator (Phase 10 step 3) checks grounding against the row's *source* text, which is only
  possible because the model is required to reproduce that text rather than reinterpret it.
- `generic_name` stays a Spark-derived field (unambiguous cases only, per the existing pipeline)
  rather than becoming something the LLM is trusted to supply.
- Training runs are not reproducible on a machine without Apple Silicon without re-deriving a
  CUDA/CPU training path; this is accepted because the production target is also a small CPU
  host, not a GPU server.

---

## Amendment, 2026-11-22 — the 0.5–1B production cap is lifted to 1.5B

**Context.** Step 2's zero-shot comparison (three Apache-2.0 candidates, scored on the
validation split, never the test split) measured:

| Model | JSON valid | Right schema | Grounded | Overall field F1 | Time/row (MPS, bf16) |
|---|---|---|---|---|---|
| Qwen2.5-0.5B-Instruct | 100% | 98.1% | 97.2% | 19.7% | 1.20s |
| **Qwen2.5-1.5B-Instruct** | 100% | 100% | 93.7% | **41.1%** | 4.42s |
| SmolLM2-360M-Instruct | 49.1% | 7.5% | 91.7% | 2.3% | 2.42s |

SmolLM2-360M is eliminated outright: it cannot reliably produce parseable JSON zero-shot, let
alone the right fields. Between the two Qwen sizes, 1.5B roughly doubles 0.5B's field F1.

**The 0.5–1B cap's original reasoning no longer fits this candidate's actual job.** It assumed
"has to run every month in the pipeline" meant a bulk-size workload worth optimising per-row cost
for. But the fallback only ever runs on **low-confidence rows** — about 103 archive-wide, a
handful a month — not a bulk pass over every row. At 4.42s/row even on a modest CPU host (this
measurement is on Apple Silicon's MPS backend; a slower CPU-only server would still be seconds,
not minutes, for a handful of rows), the per-row cost this cap was protecting against is not the
real constraint.

**Decision (Harith, 2026-11-22, choosing between keeping the cap, lifting it, or fine-tuning both
sizes before deciding):** lift the production cap to **Qwen2.5-1.5B-Instruct**. Step 4 fine-tunes
this model only, not both sizes — the zero-shot gap is already large enough, and a volume-driven
cost concern that doesn't apply to a rarely-invoked fallback isn't a reason to double step 4's
training cost to re-confirm it with LoRA adapters too.

**Caveat worth carrying into step 4's report:** `manufacturer` and `product_name` scored near 0%
F1 on **every** candidate despite grounding staying above 90% throughout — the models are not
inventing values, they are producing text that fails the strict whitespace-collapsed exact-match
`outcome()` scoring (the same rule the parser is held to) on long, multi-line, multi-word fields.
A parser that copies a cell verbatim either matches exactly or doesn't; a generative model
producing a slightly different line-wrap or word order on a long address gets zero credit for
being close. This is reported as a finding about the metric's harshness on long fields, not
evidence that fine-tuning on these fields is hopeless.

---

## Amendment, 2026-11-23 — training moves to Colab; the "train locally" half of this ADR's
## original decision is reversed

**Context.** Step 2 only measured *forward*-pass speed on Apple Silicon's MPS backend before
picking Qwen2.5-1.5B-Instruct (4.42s/row). Step 4 needed the *backward* pass, and its actual
cost turned out not to scale the way the forward pass had:

| Sequence length | MPS, `sdpa` attention (the default) | MPS, `eager` attention |
|---|---|---|
| 200 tokens | 2.52s | 1.64s |
| 400 tokens | **134.90s** | **43.68s** |

That is a **cliff, not a curve** — ordinary attention cost scales with the *square* of sequence
length, which predicts roughly a 4x slowdown from 200 to 400 tokens, not 27–53x. Real training
rows (step 1's 737 examples) average 360–505 tokens once the prompt and chat template are
applied, which lands every one of them past the cliff. The eager-attention path is measurably
better but still on the wrong side of it. A plain training loop (no `transformers.Trainer`) made
no difference either — an earlier working note in this project's own history had pinned the
blame on `Trainer`'s overhead, which this amendment corrects: removing it changed nothing
(~111s/example either way). The actual cause is specific to how this version of PyTorch's MPS
backend handles the backward pass at this sequence-length range, most likely a kernel silently
falling back to a slow path past some internal threshold - a known general class of MPS rough
edge, not a bug in this project's code. At the measured rate, the planned run (737 examples x 3
epochs) would take roughly 60 hours on this Mac.

**Decision (Harith, 2026-11-23, choosing between chasing further MPS-specific fixes, shrinking
every training sequence to fit under the cliff, or moving the training step to a different
machine):** train on Google Colab's free GPU tier instead. A CUDA GPU's attention kernels do not
share this MPS-specific fallback behaviour. This reverses this ADR's original "fine-tuning runs
on this Mac" decision from local-only to local-inference-plus-remote-training:

- **What stays the same:** the output schema (values as printed), the prompt format
  (`prompting.py`), the LoRA configuration, and the eventual production target (a small model
  that still has to run inference on a modest CPU host - training location and inference
  location are independent choices, and only the first one is changing here).
- **What moves:** only the training *run* itself (`llm/notebooks/colab_train.ipynb`, inlining
  copies of `prompting.py`'s and `dataset.py`'s logic rather than installing the monorepo's
  cross-package plumbing into a one-off Colab environment). `train.py` stays in the repo as the
  tool that proved the pipeline correct at small scale and as the reference implementation the
  notebook's copies are kept in sync with by hand.
- **The data trade-off, named rather than glossed over:** `data/llm-training/train.jsonl`
  contains real CDSCO text and was deliberately kept off this Mac's git history (ADR 0003). Using
  it in Colab means uploading it to a private, personal Colab session - not publishing it (the
  concern ADR 0003 and `docs/permissions.md` actually govern is the *public live site*, not a
  researcher's own private tooling), but a real, conscious exception to "stays on the Mac" that
  this ADR records rather than leaves implicit. The file is deleted with the Colab runtime; only
  the trained adapter (a few MB of LoRA weights, no row-level text) comes back.
- **`publish_run.py`** is the seam between the two machines: it reads a finished run's
  `run_info.json` and `adapter/` directory (produced by either `train.py` locally or downloaded
  from Colab) and logs the run to MLflow. It never loads a model, so - unlike `train.py` - it is
  allowed to need Docker up.

## Consequences (this amendment)

- Phase 10 is no longer trainable end-to-end from a single `uv run` command on the Mac; step 4's
  real run needs a human to open the notebook, select a GPU runtime, and run it - closer to the
  project's existing "manual_drop" pattern for steps that need a person's hands than to the rest
  of the pipeline's automation.
- `docs/llm-extraction-report.md` (step 5) should record which device actually trained the
  published adapter (`run_info.json`'s `device` field), since Colab's and the Mac's bf16 numerics
  can differ in the last few bits - unlikely to matter at the field-level F1 this phase reports,
  but worth being able to say rather than assume.
- If a future phase needs CI to retrain this model automatically, that CI job cannot run on
  GitHub's standard runners either (no GPU) - it would need its own remote-GPU step, which is
  explicitly out of scope for this project.

## Amendment, 2026-11-23 (third) — Kaggle Notebooks as a second training host

**Context.** One full training run (737 examples x 3 epochs on a T4, about 40 minutes) used about a
day of Colab's free GPU allowance. The next attempt got "You cannot currently connect to a GPU due
to usage limits". Two runs have already been lost to notebook bugs, so a retry that depends on a
daily reset turns each mistake into a lost day.

**Decision (Harith, 2026-11-23, choosing over paying for Colab compute units and over waiting for
the reset):** add **Kaggle Notebooks** (free GPU, rationed weekly rather than daily) as a second
host. This is a new service under CLAUDE.md §4, so it is recorded here.

- **One notebook, not two.** `llm/notebooks/colab_train.ipynb` detects `/kaggle/input` and differs
  in exactly two places: how `train.jsonl` gets in (Colab's upload widget, or a Kaggle dataset)
  and how the run gets out (Colab's disk, Drive and a download, or `/kaggle/working/` and Kaggle's
  Output pane). The prompt, tokenization, LoRA config and training loop are shared. A second
  notebook would be a second hand-synced copy of `prompting.py` and `dataset.py`, and that copy is
  the one that drifts. The filename keeps "colab" so existing links and history still resolve.
- **The data trade-off is the same one, made a second time, and stated again.** Kaggle has no
  upload widget, so `train.jsonl` (real CDSCO text, ADR 0003) has to become a Kaggle **dataset**,
  which must be created **Private**. That copy outlives the session, unlike Colab's, so it should
  be deleted from Kaggle once the adapter is safely published. The notebook reads it in place from
  the read-only `/kaggle/input/` and never copies it into `/kaggle/working/`, because Kaggle saves
  that folder as the notebook's output.
- **P100 is refused in cell 1.** Kaggle offers a P100 beside the T4. It has compute capability
  6.0 and no native bfloat16, and recent PyTorch CUDA builds have dropped Pascal kernels, so it
  would fail late and confusingly. The T4 is what the first run actually trained on.
- `run_info.json` gains a `platform` field (`colab` / `kaggle`) beside `device`, so step 5's report
  can say which host produced the published adapter.
