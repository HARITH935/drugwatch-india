# Phase 10 step 5 — the single-use test

Adapter `kaggle-20261124-043743` (`Qwen/Qwen2.5-1.5B-Instruct`, trained on kaggle, 556 examples) scored against the test split's 69 labelled rows, read exactly once (CLAUDE.md §5).

*Not medical advice. Data from CDSCO public alerts.*

## Gate 1 (the plan's done-when): low-confidence test rows

Honest n = 28 field-value pairs over 6 rows, not the plan's assumed 9 (step 2 checked and declined to pad this; PROGRESS.md step 1).

| Parser baseline | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| low-confidence rows | 24 | 0 | 4 | 100.0% | 85.7% | 92.3% |

| LLM-merged | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| low-confidence rows | 24 | 4 | 4 | 85.7% | 85.7% | 85.7% |

**Gate 1: FAIL** (85.7% vs baseline 92.3%).

## Gate 2 (this phase's added gate): the whole test split

| Parser baseline | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| all 69 rows | 402 | 0 | 4 | 100.0% | 99.0% | 99.5% |

| LLM-merged | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| all 69 rows | 402 | 4 | 4 | 99.0% | 99.0% | 99.0% |

**Gate 2: FAIL** — F1 FELL (99.0% vs baseline 99.5%), and 0 of 4 accepted substitutions were ungrounded (must be 0 - `validator.merge` checks grounding before accepting any value).

## By field, whole test split

| Parser baseline | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| product_name | 69 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| batch_no | 68 | 0 | 1 | 100.0% | 98.6% | 99.3% |
| mfg_date | 64 | 0 | 1 | 100.0% | 98.5% | 99.2% |
| expiry_date | 64 | 0 | 1 | 100.0% | 98.5% | 99.2% |
| manufacturer | 68 | 0 | 1 | 100.0% | 98.6% | 99.3% |
| failure_reason | 69 | 0 | 0 | 100.0% | 100.0% | 100.0% |

| LLM-merged | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| product_name | 69 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| batch_no | 68 | 1 | 1 | 98.6% | 98.6% | 98.6% |
| mfg_date | 64 | 1 | 1 | 98.5% | 98.5% | 98.5% |
| expiry_date | 64 | 1 | 1 | 98.5% | 98.5% | 98.5% |
| manufacturer | 68 | 1 | 1 | 98.6% | 98.6% | 98.6% |
| failure_reason | 69 | 0 | 0 | 100.0% | 100.0% | 100.0% |

The LLM's reply parsed as exactly the right schema on 67 of 69 rows (97.1%).

4 of 69 rows had a field the LLM's answer actually changed (the rest: either nothing was low-confidence, or the LLM's answer failed grounding/plausibility and the parser's own value was kept).

## Why gate 1 made things worse, not just failed to improve them

All 4 substitutions, on both gates, are the same one row: the archive's single genuine parser
mistake in the whole test split (identified independently while building this script, before any
adapter was scored - `PROGRESS.md` Phase 10 step 4's planning note). It is a **two-part pack**: one
printed row covering two batches, so the PDF prints two batch numbers, two mfg dates, two expiry
dates and two manufacturers in the same cell. The parser's own warning is `"a label appears twice
(a multi-part pack): not split"`, and it left those four fields blank rather than guess which half
went where. The label records the honest answer as **both values joined with `" | "`**
(`"911805 | WB7L20"`), because that is genuinely what the batch is.

The LLM read the row and picked ONE of the two real, printed values for each field - which
`grounded()` correctly accepts (it really is printed) and `plausible()` correctly accepts (it is a
well-formed batch number, date, name). Nothing was invented; CLAUDE.md §5's rule held. But a
grounded, well-formed, *half-right* answer is not equal to the compound label under exact-match
scoring, so each of these four fields went from a clean miss (FN: blank, safe, wrong) to a wrong
answer (FP+FN: confidently wrong). That is why precision falls (85.7% / 99.0%) while recall stays
exactly where it was (85.7% / 99.0% on both subsets) - the model never produced a value for a field
it previously got right or correctly left blank; it only touched the one row it was allowed to
touch, and on that row, grounding cannot distinguish "half the real answer" from "the whole real
answer" because both are literally printed text.

## What this does not cover

- **Metric harshness, carried from step 2**: `manufacturer` and `product_name` are scored on an exact, whitespace-collapsed match - the same bar the parser is held to - so a reply that is grounded and almost right still scores zero credit for not being byte-identical.
- **The held-out-layout experiment** (train with one layout family excluded, test on it) was approved as reported-but-non-gating and is not run here; it needs a second training run and is deferred.
- **A row the parser lost entirely** is out of this step's scope (and this run) - the test split has none.
