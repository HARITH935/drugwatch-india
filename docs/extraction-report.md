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

All families run on one engine, `extraction/src/drugwatch_extraction/table_parser.py`: **the header decides the
fields.** Each family supplies a vocabulary (field → phrases its header cell can contain). The header row (≥ 4
matching cells, one of them S.No) gives every column a field name and an x-position; every cell is assigned to the
column it sits under. Header cells no vocabulary knows still get a column (`other_<words>`) and are reported.
Values are kept **as extracted** (bronze rule): wrapped cells keep their line breaks, dates stay as printed.
Fields with the same meaning share a name across families: B's "NSQ Result" and C's "Reason for failure" are both
`failure_reason`.

### 2.1 Family B: NSQ lists, Apr 2024 – Jun 2025 (2026-11-08)

`family_b.py` (vocabulary only).

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

### 2.2 Family C: spurious and combined lists, Aug 2024 – Jun 2025 (2026-11-09)

`family_c.py` (vocabulary only). **10 files → 24 rows**, no serial gaps, no unknown header cells.

- **Column drift handled by the header, no special cases:** Aug 2024 has `drawn_from` and no `remarks`; Sep 2024
  has no `remarks`; Jun 2025's merged name cell (12 header cells) still gives the usual 10 columns.
- The Jan 2025 "Revised" combined list holds one entry, **serial 23**: serial gaps are counted from the first serial,
  and `first_serial` is reported (family B requires 1).
- Aug 2024: 7 one-column "tables" set aside are boxes nested inside product-name cells; every fragment is also in
  the parsed product names, so nothing is lost.
- **Agreement with the portal:** Jun 2025 is the only month where the PDFs and the portal's spurious list overlap:
  **4 of 4 batches match**, nothing extra either side.

### 2.3 Family F: spurious list, Apr 2024 (2026-11-09)

`family_f.py` (vocabulary only, no engine change). **1 file → 5 rows**, no gaps, no unknown headers, nothing set
aside. Rows are grouped by state: full-width rows ("NCT of DELHI": rows 1–4, "JHARKHAND": row 5) are section rows,
so each record carries its state. Two columns of its own: `sales_outlets` (where the fake stock was found) and
`manufacturer_response` (the genuine company's reply). No portal answer key: the portal's spurious list starts Jun 2025.

> **Caution for Phase 3 and the Phase 7 risk score.** In a *spurious* list, "Manufactured by (as per label)" is the
> name printed on the **fake** pack, usually the genuine company whose brand was copied. Spurious rows (families C
> and F) must never be counted against that company (CLAUDE.md §6).

### 2.4 Family A: vaccine lists, Jul 2017 – Apr 2023 (2026-11-09)

`family_a.py` (vocabulary only). **11 files → 16 rows** (1–3 per file), no gaps, no unknown headers, nothing set
aside. The title row and "A. Central Laboratories" above each header are section rows.

- **Agreement with the portal** (2019 onwards, 5 files): **7 of 7 batches match**. One more row prints `--` for its
  batch (no number), so there is nothing to match.
- **Mar 2022 starts at serial 3** (3, 4, 5). The page holds nothing else, so that is CDSCO's own numbering, not a
  missed row; `first_serial` records it.
- **Kept as extracted, for Phase 3 and the step-5 confidence flag:** one Feb 2018 manufacturer cell holds two texts
  printed on top of each other (`2M0/s1 0B0i`), some "Manufactured By" cells say `Spurious`, two Sep 2018 rows share a
  batch (two results for one batch).

### 2.5 Family D: combined lists, May and Aug 2018 (2026-11-09)

`family_d.py`. **2 files → 77 rows** (43 + 34), no gaps, no unknown headers, nothing set aside.

The third column prints **four values in one cell**, each labelled: `B. No.: … , Mfg dt: … , Exp dt: … , Mfd by: …`.
**Decided by Harith:** bronze keeps the cell exactly as printed (`batch_details`) **and** fills `batch_no`,
`mfg_date`, `expiry_date`, `manufacturer` by cutting at CDSCO's own labels. Only the comma between two labelled parts is
dropped; values are otherwise as printed. The labels are perfectly consistent: all four, spelled the same, in every cell.

- **75 rows split.** The other **2 are two-part packs** (a powder plus the liquid it's mixed with: May row 8, Aug row 2),
  each part with its own batch, dates and maker, and one part with no `Mfd by:` label at all. A label appearing twice means
  the cell is **not split**: split fields stay empty, the original is kept, and the row gets a **warning**. Guessing could
  pair a batch with the wrong maker; these are "hard rows" for the Phase 10 LLM fallback.
- New in `ParseResult`: `warnings` (row index, message) for rows kept with a known problem. Step 5's confidence flag
  will read them.
- No portal answer key: the portal starts in 2019.

### 2.6 Other families

To come: E.

## 3. Accuracy against the labelled eval set (steps 7–8)

To come: field-level precision, recall and F1.
