# Labelled eval set: design and labelling guide

The answer key for extraction quality (plan §9 Phase 2 steps 7–8, Phase 10). About 300 rows of the CDSCO PDFs,
labelled by hand from the PDF itself. Step 8 compares the parser's output with these labels (field-level precision,
recall and F1); Phase 10 trains and tests the LLM extractor on them.

## 1. The sample and the split (fixed 2026-11-10)

- **Sample:** up to 12 random rows from **every** CDSCO PDF (smaller files whole), seed 2026: **309 rows** from all
  44 PDFs, all 28 alert months and all six layout families, including 29 low-confidence rows.
- **Split, by whole PDF:** a PDF's rows are all in the same split, so the LLM is never tested on a file it was trained
  on. Within each layout family, each PDF (in a seeded random order) goes to the split furthest below its target share
  (test 20%, validation 20%, train 60%).

  | Split | Rows | PDFs | Families |
  |---|---|---|---|
  | train | 187 | 27 | A 11, B 132, C 15, D 12, E 12, F 5 |
  | validation | 53 | 8 | A 2, B 48, C 3 |
  | test | 69 | 9 | A 3, B 48, C 6, D 12 |

  Families E and F have one PDF each, so they are only in train. Low-confidence rows: train 18, validation 5,
  test 6. 2 rows carry a parser warning; 23 rows continue onto a second page.
  **Caution for Phase 10:** family E repeats family A's 16 vaccine batches, so A rows in validation/test have
  near-copies in train (E). Phase 10 should leave E out of training when it reports test scores.
- **Rules:** the **test split is never used for training or tuning** (CLAUDE.md §5). Parser changes made after the
  step-8 baseline are reported separately from it. The labelling tool doesn't show the split, so it can't influence
  the labels.
- **Row ID:** file SHA-256 + the page the row starts on + its printed S.No (unique across the archive; S.No alone is
  not). A label survives parser changes: a row the parser loses becomes an unmatched label, which step 8 counts as a miss.

The sample is in `extraction/eval/manifest.csv` (committed: row IDs only, no CDSCO text). `eval_set --sample` refuses
to overwrite it: to redraw, delete it deliberately and record why in `PROGRESS.md`. A local test checks that the
committed manifest is exactly what the code draws from bronze.

## 2. Where the labels live (ADR 0003)

Labels contain real CDSCO values, and CDSCO data isn't published until permission is recorded (`docs/permissions.md`).
So, as Harith decided:

- `data/eval-set/labels.jsonl`: the labels, one JSON object per row. **Git-ignored** (`data/`), never committed.
- `data/eval-set/pages/`: the page pictures the tool makes. Git-ignored; safe to delete (they are re-made).
- **Backup:** RustFS and the laptop are the same disk. After each session, copy the label file to a private place, e.g.

  ```bash
  mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/drugwatch-labels
  cp data/eval-set/labels.jsonl ~/Library/Mobile\ Documents/com~apple~CloudDocs/drugwatch-labels/
  ```

## 3. How to label

```bash
cd extraction
uv run --env-file ../.env python -m drugwatch_extraction.label
```

For each row the tool opens a picture of the PDF page in Preview (in the background: put Preview and the terminal side
by side) with the row **outlined in red**. A row that continues on the next page also opens that page. Then it asks
field by field, showing the parser's value in brackets:

| You type | Meaning |
|---|---|
| Enter | the value shown is exactly what the PDF prints |
| text | what the PDF prints instead |
| `/b` | the cell is blank |
| `/u` | you can't read it (e.g. two texts printed on top of each other) |
| `/q` | stop; every finished row is already saved, and the next run continues where you stopped |

At the end of a row, type a note if something was odd (or just Enter). A row is saved the moment you finish it. Each
row starts with its number ("Row 37 of 309"); to correct it later, run the tool with `--redo 37`: the new label
replaces the old one.

**The one rule that matters: look at the picture before pressing Enter.** Checking pre-filled values makes it easy to
accept a wrong one. Compare character by character, especially batch numbers and dates (`O`/`0`, `I`/`1`, a missing or
extra character, a value from the neighbouring cell or row).

## 4. What to type

- **Exactly what the cell prints**: same characters, case and punctuation. Labels printed inside the cell stay
  (`B.no: TB-1201`).
- **Spaces and line breaks don't count** when scoring, so type everything on one line. `TB-⏎1201` and `TB-1201` are
  the same, and so are letter-spaced words (`A s s a y` = `Assay`).
- **The whole cell, and only this row's cell.** The product name includes the brand in brackets; the manufacturer
  includes the full address. If the parser added text that isn't in this row's cell (a footnote, the next row), remove
  it. If it missed part of the cell (e.g. the end of an address on the next page), add it.
- **Placeholders as printed:** `NIL`, `NM`, `Not mentioned`, `--`, `N/A`, `Spurious` are the cell's text: type them.
  Only a truly empty cell is `/b`.
- **Dates as printed:** `Feb'16`, `0 9 / 2 0 2 4 .`, `45200` (an Excel day number), "Best before 36 months from the
  date of Mfg." Don't convert anything: that's Phase 3's job.
- **Two values in one cell** (two batches, two dates): type the whole cell as printed, both values included.
- **Family D (2018 combined lists):** the batch number, both dates and the manufacturer all come from the one "Batch
  No./Date of Manufacture" cell. Type the text after each label (`B. No.:`, `Mfg dt:`, `Exp dt:`, `Mfd by:`), without
  the comma before the next label. In a **two-part pack** (a label printed twice), type both parts' values in order,
  separated by ` | `.
- **Family F (Apr 2024 spurious list):** has no failure-reason column, so the tool doesn't ask for one.

## 5. How step 8 will score (preview)

Per field, a parser value counts as correct when it equals the label with all spaces and line breaks removed. A blank
label (`/b`) is matched by a blank parser value. An unreadable label (`/u`) is left out of the score. A label whose row
the parser no longer finds counts as a miss for every field. Precision, recall and F1 are reported per field, per layout
family and per split.
