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

### 2.1 Family B: NSQ lists, Apr 2024 – Jun 2025 (2026-11-08)

`extraction/src/drugwatch_extraction/family_b.py`. Values are kept **as extracted** (bronze rule): wrapped cells
keep their line breaks, dates stay as printed.

- **19 files → 1,179 rows.** Serial numbers run 1…N with **no gaps** in every file; no row left unrecognised.
  The only rows set aside are 1-column footnote boxes (2 per file in most months), which are never merged.
- **Rows cut by a page break** (empty S.No at the top of a page) are merged into the row above: up to 14 per file.
- **Columns are matched by position**, using the header's cell positions from page 1. Apr 2024 page 4 is drawn
  as a 12-column grid (name and manufacturer split over 3 cells each); position matching maps it back to 8 fields.
- **Duplicated lines** from split cells (a cell holding a whole address that the next rows repeat) are not added twice.

**Agreement with the portal** (batch numbers, same month and lab type, ignoring spaces and line breaks):

| | Central (10 months) | State (9 months) | All |
|---|---|---|---|
| PDF batches also in the portal | 492 / 516 = 95.3% | 602 / 650 = 92.6% | **1,094 / 1,166 = 93.8%** |
| Portal batches also in the PDF | 492 / 540 = 91.1% | 602 / 610 = 98.7% | **1,094 / 1,150 = 95.1%** |
| Months matching 100% both ways | 4 | 5 | **9 of 19** |

Where both sources list the same number of rows, **every remaining mismatch is the portal's representation, not
a parser error**: the portal drops leading zeros (`04010026` → `4010026`, `0081` → `81`) and loses characters
(`CHI – 40139` → `CHI ? 40139`). The other differences are rows that only one source lists (e.g. central Jun 2025:
55 PDF rows, 81 portal rows), which Phase 3 has to handle as a source difference.

**Quirks kept as extracted, for Phase 3 to clean:** letter-spaced words (`A s s a y`: real space characters in the
file, not a pdfplumber setting), batch numbers wrapped inside a cell (`RDCPH230\n02`), a serial's dot landing in
the next cell (`11` | `. DofloxOZ`), dates with trailing dots (`12/2022.`), placeholders (`Nil`, `-`).

### 2.2 Other families

To come: A, C, D, E, F.

## 3. Accuracy against the labelled eval set (steps 7–8)

To come: field-level precision, recall and F1.
