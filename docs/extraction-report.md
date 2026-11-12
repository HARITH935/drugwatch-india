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
- **Short date headers, fixed in step 5.** Apr 2024's state-lab pages print `Mfg Dt` / `Exp Dt`. Step 2's vocabulary
  missed them, so those 17 rows had their dates under `other_mfg_dt` / `other_exp_dt` (an unknown header that no
  test checked). Step 5's field profile found it; the archive test now fails if any file has an unknown header.

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
  printed on top of each other (`2M0/s1 0B0i`; since step 5 the engine detects this and warns, §2.9), some "Manufactured By" cells say `Spurious`, two Sep 2018 rows share a
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

### 2.6 Family E: bulk vaccine file, 2017 – 2023 (2026-11-09)

`family_e.py`. **1 file → 16 rows**, no warnings, no unknown headers, nothing set aside.

- **One table and one year per page.** Page 1's title is the table's first row; pages 2–5 print theirs above the table.
  Each row gets its own page's title as `section` and the year as `report_year`: 2017 ×2, 2018 ×6, 2019 ×2,
  2022 ×5, 2023 ×1 (no pages for 2020–2021). Serial numbers restart on every page, so they're checked page by page.
- **Engine change found here:** each page's table draws its columns at different positions, so a repeated header now
  **replaces** the column positions (before, the first header won, which shifted cells and lost the 2023 row). All other
  families' results were unchanged; a new engine test fails with the old rule.
- **Same 16 batches as family A**, plus `status`, `sample_source` and `regulatory_action`. With the portal (2019+), the
  same vaccine finding can appear in three sources: **Phase 3 must count it once.**

### 2.7 Summary

| Family | Files | Rows | Checked against the portal |
|---|---|---|---|
| A vaccine lists | 11 | 16 | 7 / 7 batches (2019+) |
| B NSQ lists | 19 | 1,179 | 93.8% / 95.1%, remaining gaps are the portal's |
| C spurious / combined | 10 | 24 | Jun 2025: 4 / 4 |
| D combined 2018 | 2 | 77 | (portal starts 2019) |
| E bulk vaccine file | 1 | 16 | same batches as A |
| F spurious Apr 2024 | 1 | 5 | (portal spurious starts Jun 2025) |
| **All** | **44** | **1,317** | |

pdfplumber's ruled-table finder handled every family: **Camelot was not needed.**

### 2.8 Provenance (step 4, 2026-11-09)

`extraction/src/drugwatch_extraction/extract.py` is the one entry point: it reads a PDF and its `raw/` sidecar, checks
the bytes still match the sidecar's SHA-256 (otherwise no records: provenance must name the exact bytes), classifies
the file, runs that family's parser, and turns every row into a **record**: the row's fields plus

| Field | Meaning |
|---|---|
| `source_key`, `source_sha256` | the PDF in `raw/` and its fingerprint |
| `source_url` | the CDSCO URL it was downloaded from: the "link to the original document" (CLAUDE.md §6) |
| `source_dataset`, `alert_month`, `file_id`, `listing_title` | what CDSCO's alerts page said about the file |
| `family`, `page`, `pages`, `row_index`, `section` | where in the file the row sits |
| `extraction_method`, `extractor_version` | `rule` (Phase 10's LLM fallback will write `llm`) and the parser code version |
| `warnings` | problems the parser found in this row |
| `confidence`, `confidence_reasons` | `high` / `low` and why (step 5, §2.9) |

**Whole archive: 44 PDFs → 1,317 records**, every one with a `https://cdsco.gov.in/` source URL, a SHA-256, a page and a row
number; 3 records carry warnings (the 2018 two-part packs and, since step 5, the overprinted Feb 2018 cell). Run: `uv run --env-file ../.env python -m drugwatch_extraction.extract --all`.

### 2.9 Confidence flag (step 5, 2026-11-09)

`extraction/src/drugwatch_extraction/confidence.py`: `assess(record)` gives every record `confidence` (`high` / `low`)
and `confidence_reasons`. The plan's rule: **all required fields present and well-formed = high.**

- **Required:** product name, batch number, manufacturing date, expiry date, manufacturer, and failure reason. Family
  F (the Apr 2024 spurious list) has no failure column, so it isn't required there.
- **High** also needs **no parser warning** for the row.
- Checks read a compact copy of each value (spaces and line breaks removed), so `0 9 / 2 0 2 4 .`, `Dec/202⏎3`,
  `Feb'16` and `June, 2023` are dates. Months must be 1–12, days 1–31, four-digit years 1990–2049. The record keeps the
  value as extracted.

| Problem | Meaning |
|---|---|
| `missing` | empty cell, or no such column |
| `not stated` | the PDF prints a placeholder: `NIL`, `NM`, `Not mentioned`, `--`, `N/A`, `No expiry`; or a manufacturer cell saying `Spurious` |
| `not a date` | a rule instead of a date ("Best before 36 months from the date of Mfg."), two dates in one cell, `30-062025` |
| `Excel day number` | a date printed as a spreadsheet's day count: `45200` = 1 Oct 2023 (days since 1899-12-30) |
| `no digit` / `several values` | a batch number with no digit / two batches in one cell (which one failed?) |
| `no name` | a product or manufacturer cell with no word in it |
| `parser warning` | the parser flagged the row; the messages are in `warnings` |

**Whole archive: 1,214 high (92.2%), 103 low**: B 86, A 8, E 7, D 2; every C and F row is high. One record can have
several reasons:

| Reason | Records | | Reason | Records |
|---|---|---|---|---|
| `expiry_date: Excel day number` | 31 | | `mfg_date: missing` | 16 |
| `mfg_date: Excel day number` | 25 | | `batch_no: not stated` | 9 |
| `mfg_date: not stated` | 22 | | `parser warning` | 3 |
| `expiry_date: not a date` | 17 | | `mfg_date: not a date` | 2 |
| `expiry_date: missing` | 17 | | `batch_no: several values` | 2 |
| `manufacturer: not stated` | 16 | | `batch_no: missing` | 2 |
| `expiry_date: not stated` | 16 | | `manufacturer: missing` | 2 |

**Only 3 low rows come from the parser** (the two 2018 two-part packs, the overprinted cell). The other 100 are low
because of what the PDF itself prints: the extraction is right, the source value isn't a usable date or name. This
matters for Phase 10: an LLM fallback can only help where the parser misread the PDF, and the reasons let it select
those rows. Phase 3 can convert Excel day numbers and compute "N months from the date of Mfg." expiries.

**Overprint detection (engine).** Two *different* characters on one line whose boxes overlap by at least half the
narrower one's width form an overlapping pair. A cell with **2 or more** pairs is overprinted: the row is kept as
extracted and gets a warning. Across the archive the one known cell has 6 pairs; two other cells have a single `al`
pair, which is just a tight font, and the same letter drawn twice (bold printing) never counts.

### 2.10 Bronze Parquet (step 6, 2026-11-09)

`extraction/src/drugwatch_extraction/bronze.py` writes every PDF's records to the `bronze` bucket with **pyarrow**
(approved by Harith, ADR 0007).

- **One Parquet file per source PDF**, at the PDF's `raw/` key with `.parquet` instead of `.pdf`
  (`bronze/cdsco-pdf/<dataset>/<month>/<file_id>/<sha256>.parquet`). The name is still the source PDF's SHA-256;
  re-running replaces the file, never adds a copy.
- **One schema for every family** (37 columns), declared in code:
  - provenance keeps its types (`page`, `row_index`: integers; `pages`, `warnings`, `confidence_reasons`: lists);
  - every row field any family can produce is a text column. **Null = this layout has no such column; `""` = the
    cell was blank.** A test checks the column list against every family's vocabulary;
  - a header no vocabulary knows (`other_*`) goes into an `extra_fields` map instead of a new column;
  - any other unexpected field stops the write (pyarrow on its own would silently drop it), and pyarrow refuses to
    write a file where a required provenance column (source key, SHA-256, page, ...) is null.

**Whole archive: 44 files, 1,317 rows, 759 KB.** The command reads every file back from RustFS and checks the row
count and the schema (`read back: 44 files, 1317 rows, schema identical: True`). Run:
`uv run --env-file ../.env python -m drugwatch_extraction.bronze --all`.

**A hang found on the way (macOS).** The first full run wrote and verified everything, then never exited. A stack
sample showed the main thread inside `exit()`, in the destructor of one of Arrow's C++ thread pools, waiting forever
for a pool worker that was itself waiting. It happened in 2 of 2 full runs and in 1 of 2 read-only runs: a race at
shutdown, not a data problem. Counting the process's threads showed the cause precisely:

| How a Parquet file is read | Arrow pool threads left running |
|---|---|
| `pq.read_table(io.BytesIO(data))` (the usual way) | 4–5 |
| … with `use_threads=False` | 1–2 |
| `pq.ParquetFile(pa.BufferReader(data)).read(use_threads=False)` | **0** |

Bronze files are a few KB, so threads gain nothing: `from_parquet()` uses the last line, and with no pool threads
there is nothing to wait for at exit. After the change: 0 pool threads at the end of a full run, and 4 of 4 full
runs exited normally. A unit test fails if reading ever starts threads again (checked by switching back to the old
call: the test failed). Writing never started pool threads.

## 3. Accuracy against the labelled eval set (steps 7–8)

**Eval set (step 7, 2026-11-10):** 309 rows, up to 12 random rows from every PDF, split by whole PDF into train 187 /
validation 53 / test 69 rows. Design, split rules and the labelling guide: `docs/eval-set.md`. Labelling by Harith:
pre-filled values checked against a picture of the PDF page. Labels stay local (ADR 0003).

**Labels:** AI-assisted double reading (the parser's text layer vs Claude reading a picture of each row, blind to the
parser); all 12 disagreeing values decided by Harith; 309 of 309 rows labelled. Method and caveats: `docs/eval-set.md`.

### 3.1 Baseline (step 8, 2026-11-12)

`extraction/src/drugwatch_extraction/evaluate.py`. Each labelled value is compared with the parser's bronze value,
spaces and line breaks ignored: equal = TP; wrong = FP + FN (invented and missed); empty = FN; text where the cell is
blank = FP; unreadable labels are not scored; a row the parser lost counts every value as FN. Pooled over all values:

| | TP | FP | FN | Precision | Recall | **F1** |
|---|---|---|---|---|---|---|
| **All 309 rows (1,846 values)** | 1,832 | 5 | 9 | 99.7% | 99.5% | **99.6%** |
| Test split (69 rows) | 402 | 0 | 4 | 100.0% | 99.0% | 99.5% |
| Low-confidence rows, all splits | 161 | 1 | 5 | 99.4% | 97.0% | 98.2% |
| **Low-confidence rows, test split (Phase 10's target)** | 24 | 0 | 4 | 100.0% | 85.7% | **92.3%** |

| Field | F1 | | Family | F1 |
|---|---|---|---|---|
| product_name | 98.7% | | A vaccine lists | 99.0% |
| batch_no | 99.8% | | B NSQ lists | 99.7% |
| mfg_date | 99.8% | | C spurious / combined | 100.0% |
| expiry_date | 99.8% | | D combined 2018 | 98.6% |
| manufacturer | 99.5% | | E bulk vaccine file | 100.0% |
| failure_reason | 100.0% | | F spurious Apr 2024 | 100.0% |

**All 9 wrong or missing values** (3 causes, all known before step 8):

| Rows | Values | Cause | Confidence flag |
|---|---|---|---|
| 149 (family D, test) | 4 FN | two-part pack: split fields left empty by design (§2.5) | low ✓ |
| 5 (family A, train) | 1 FP+FN | overprinted manufacturer: text layer garbled (§2.4) | low ✓ |
| 210–213 (family B, train) | 4 FP+FN | the S.No's dot sits in the product cell's text (`. Pedxim-200`), hidden under the border in print (§2.1) | **high ✗** |

**What the baseline says, and doesn't:**
- The rule parser puts the right text in the right field for 99.6% of values. It does not measure cleaning: dates,
  placeholders and Excel day numbers are scored as printed; turning them into values is Phase 3.
- **The confidence flag misses one error type:** the stray dot (4 values) sits in rows flagged high. A check for a
  name starting with `.` would catch it. All 4 rows are in the train split, so fixing it doesn't touch the test split;
  any parser change after this baseline is reported separately from it.
- **Phase 10's target is thin:** only 6 low-confidence rows (28 values) are in the test split, and all 4 errors come
  from one row. Phase 10 should label more low-confidence rows from test-split PDFs before claiming a win.
- The labels come from two readings agreeing; an error both readings make the same way would be missed. That is unlikely
  (text layer vs picture), and the second reader's own slips surfaced as disagreements (row 249: it "corrected" a
  CDSCO typo).
- The sample is 12 rows per PDF, so small layouts weigh more than in the archive (family B: 74% of the sample, 89% of
  the archive). B scores 99.7%, so weighting by archive share would barely move the total.

**Checkpoint decision (plan §9):** extraction quality is high and no CDSCO PDF is scanned, so no re-scope is needed.
Run: `uv run --env-file ../.env python -m drugwatch_extraction.evaluate`. A local regression test fails if the overall
F1 drops below 99.6%.
