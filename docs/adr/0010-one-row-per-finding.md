# ADR 0010 — Silver holds one row per finding, and records every document that reported it

- **Status:** Accepted
- **Date:** 2026-11-13
- **Decided by:** Harith (project owner)
- **Affects:** `spark/src/drugwatch_spark/deduplicate.py`, `build_silver.py`'s schema
  (`also_reported_in`), and every count built on silver (Phase 4 marts, Phase 6 dashboards,
  Phase 7 risk-score features)

---

## Context

Phase 3 step 7 says: *"Deduplicate repeated rows across central and state lists."* Measured on the real archive
(8,322 silver rows, 2026-11-13), that is **not where the repeats are**:

- **0** groups repeat across two documents of the same source, and exactly **1** spans a central and a state list.
- The real overlap is between the two **sources**. The CDSCO portal is primary from 2019 (ADR 0004) and the alert
  PDFs run to Jun 2025, so **19 months carry rows from both**. Keyed on batch + month + maker + product, there are
  **1,186 repeated groups and ~1,197 extra rows — 1,154 of them a portal row paired with a PDF row.** About 14% of
  silver is double-counted.
- CDSCO's bulk *"Samples declared NSQ 2017-2023"* file adds **16 more rows** whose batches are already reported
  month by month (13 of its 14 batches), and which carry **no alert month at all** — the only NULL `alert_month`
  values in silver.

Two traps the data set, both found by reading real groups rather than trusting a count:

- **A batch number does not identify a finding on its own.** One maker reuses batch `TST2301` across five
  different injections (Trenbolone Acetate, Trenbolone Enanthate, Nandrolone Blend, Boldenone, Stanozolol). Keyed
  on batch + month + maker, all ten rows collapse into one "duplicate" and five distinct findings become one.
- **Some batch numbers name no batch**: `"not applicable"` (22 rows), `"not mentioned"` (7), `"nil"` (4), `"--"`
  (4), `"-"` (3), `"not given"`, `"na"` — 42 rows. Grouping on those merged unrelated medicines. Five of the seven
  are already in `manufacturer_name.py`'s `PLACEHOLDER` set.

## Options considered

| Option | Trade-off |
|---|---|
| A. Keep both rows, flag one | Nothing removed, fully auditable; but silver is then not "deduplicated" as the plan's data-layer table states, and every consumer must remember to filter. |
| B. Drop the duplicate outright | Smallest and simplest, but the second document vanishes from the record — silver could no longer show that a batch was published in both a state list and the portal. |
| **C. Keep one row, record the other documents** | One row per finding **and** provenance for every document that reported it (CLAUDE.md §5). Costs one array column and a documented merge rule. |

## Decision

**Option C.** A finding is identified by **batch number + alert month + manufacturer + product + `is_spurious`**,
with every part required; the winning row is the portal's; content gaps are filled from the row it replaces; and
`also_reported_in` lists the other documents' `source_key`s.

- **The product is in the key** — the `TST2301` case above is why.
- **Placeholder batch numbers are excluded**, reusing `manufacturer_name.py`'s `PLACEHOLDER` set plus the two
  spellings only seen in this column, rather than copying a second list that could drift.
- **Nothing merges on a missing key part.** Spark's `groupBy` treats NULL as a value, so keying on a nullable
  column quietly merges rows whose maker is merely *unknown* — which is how 10 spurious rows first appeared to
  duplicate NSQ findings, both having no canonical maker. A row missing any part gets its own id, built from
  `(source_key, page, row_index)`, proven unique across all 8,322 rows.
- **`is_spurious` is in the key**, so a counterfeit report can never merge into a manufacturer's own record
  (CLAUDE.md §6). Because `manufacturer_canonical` is always NULL on a spurious row, the maker part falls back to
  `name_on_pack` — the right identity for matching two reports of the same counterfeit, still attributed to nobody.
- **The portal row wins** (ADR 0004): on exactly these pairs its dates parse better (95% against 90%) and its text
  is cleaner, the PDF's being line-broken and carrying mojibake quotes.
- **Content columns fill gaps from the twin**, taking the first non-null value in preference order. This matters
  for 2 real rows where only the PDF carries text — one a firm's reply reading *"The actual manufacturer (as per
  label claim) has informed that the impugned batch…"*, a real company stating a batch is not theirs. Losing that
  would be the worst kind of loss.
- **Provenance columns are never blended**: `source_dataset`, `source_key`, `source_sha256`, `source_url`, `page`,
  `row_index` and `extraction_method` all describe the row that won, so one document's `page` can never sit beside
  another document's key.
- **The bulk file is dropped** — redundant, month-less, and its only extra fields (status, regulatory action) are
  not in the silver schema.
- **Exact matching only.** About 6 cross-source pairs do not match because the product text differs
  (`"Fem creme Bleach"` against `"Fem cream Bleach"`; a PDF truncating `"…Face and Body Cream"` to `"…Face and
  Body"`). They stay as two rows. Same rule as manufacturer merging (CLAUDE.md §5): a missed merge beats a wrong
  merge, and the key stays something that can be stated in one sentence. RapidFuzz on the product was rejected
  for this: `Trenbolone Acetate` and `Trenbolone Enanthate` score high and are different medicines.

## Consequences

- Silver drops from **8,322 to 7,128 rows**, measured: −16 for the redundant bulk file, −1,144 merged across two
  or more documents (1,136 groups), −34 merged inside a single document (31 groups). The 16 NULL `alert_month`
  values disappear with the bulk file, so step 8's GE suite can require that column to be present.
- **1,136 kept rows name another document** in `also_reported_in` — exactly the number of cross-document groups.
  The other 34 merges were duplicate rows *within one document*, where the array stays empty because there is no
  second document to name: it records other documents, not other rows. Anyone reconciling "1,178 rows removed but
  only 1,136 rows carry a second document" needs that distinction.
- Every merge was won by the portal, as intended: `nsq` ↔ `state-nsq` 627, `nsq` ↔ `central-nsq` 508,
  `nsq` ↔ `combined` 1.
- **Counts change meaning**: a batch flagged in both a state list and the portal is now one finding, not two. Any
  figure quoted from before this change (including Phase 2's per-source row counts) is a row count, not a
  finding count.
- `also_reported_in` is an array column, so Phase 4's dbt models unnest it to answer "which documents reported
  this batch".
- **Dedup is idempotent**, which Phase 5 depends on: its own acceptance test is *"re-runs don't create
  duplicates"*. A test asserts that running it twice changes nothing, and the winner is stable because the
  tie-break is explicit.
- Those ~6 near-miss pairs remain double-counted out of 8,322 rows, on purpose and recorded here.
- **Interview angle:** "The plan said deduplicate across central and state lists. I measured first and found that
  overlap was essentially zero — the real duplication, 14% of rows, was between the portal and the PDFs for the 19
  months both cover. The subtle part was the key: one manufacturer reuses a single batch number across five
  different steroid injections, so keying on batch + month + maker merged five findings into one, and 42 rows used
  'not applicable' as the batch number. So the key includes the product and ignores placeholder batches, and
  because Spark groups NULLs together, any row missing a key part gets an id of its own instead of being merged
  with every other row whose maker is unknown."
