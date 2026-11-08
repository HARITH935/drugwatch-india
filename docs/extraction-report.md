# Extraction report (Phase 2)

What the rule-based PDF extraction finds, and how good it is. Filled in step by step during Phase 2.
Only file-level facts and scores go here, never the extracted alert rows (ADR 0003: CDSCO data isn't
republished until permission is recorded in `docs/permissions.md`).

---

## 1. Classification (step 1, 2026-11-08)

Every CDSCO PDF in `raw/cdsco-pdf/` is classified before parsing (`extraction/src/drugwatch_extraction/classify.py`):

- **Text or scanned:** a page is *text* with ≥ 50 characters, *scanned* with fewer characters and images over
  half the page, otherwise *blank*. Scanned pages would need OCR, which isn't in the stack.
- **Layout family:** read from the header **cells** of the first table rows on the first two pages, never from
  the file name or date. A file matching no family is reported as `unknown` and the run fails (exit status 1).

**Result: all 44 PDFs are text (251 pages, no scanned page, 1 blank page) and all have a known family.**

| Family | What | Files | Months |
|---|---|---|---|
| A | Vaccine lists (central) | 11 | 2017-07, 2017-09, 2018-01, 2018-02, 2018-04, 2018-09, 2019-03, 2019-04, 2022-03, 2022-06, 2023-04 |
| B | NSQ lists | 19 | central 2024-04 – 2024-07, 2025-01 – 2025-06; state 2024-05 – 2024-07, 2025-01 – 2025-06 |
| C | Spurious / combined lists | 10 | spurious 2024-08 – 2024-11, 2025-02 – 2025-06; combined 2025-01 |
| D | Combined lists 2018 | 2 | 2018-05, 2018-08 |
| E | Bulk vaccine file | 1 | 2017 – 2023 |
| F | Spurious list Apr 2024 | 1 | 2024-04 |

Column details per family: `docs/data-sources.md` §7.1.

**First run found 25 files `unknown`.** The first rules matched header phrases in the page's running text, but a
header whose cells wrap onto two lines is read across all columns there ("Product/Drug Batch No. … Name Date"),
so phrases broke. Matching inside table cells fixed it, and showed that B uses two names for its drug column and
that April 2024's spurious list is a separate layout (F). This is why the classifier fails loudly on `unknown`.

**Reproduce** (from `extraction/`, RustFS up):
```bash
uv run --env-file ../.env python -m drugwatch_extraction.classify     # table per file, totals, exit 0
uv run --env-file ../.env pytest -m integration                         # asserts the counts above
```

---

## 2. Rows extracted (steps 2–6)

To come.

## 3. Accuracy against the labelled eval set (steps 7–8)

To come: field-level precision, recall and F1.
