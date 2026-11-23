# PROGRESS — DrugWatch India

Live checklist. Update after every step. Full plan: [DRUGWATCH_PHASES.md](DRUGWATCH_PHASES.md).

**Current phase:** Phase 10 — LLM Extraction.
**Next:** step 4 is waiting on Harith — open `llm/notebooks/colab_train.ipynb` in Google Colab
(GPU runtime), upload `data/llm-training/train.jsonl`, run all cells, download the adapter zip
back into `data/llm-training/runs/<run_name>/`, then (Docker up) run
`uv run --env-file ../.env python -m drugwatch_llm.publish_run <run_name>` from `llm/`.

---

## Phase status

| Phase | Name | Status |
|---|---|---|
| 0 | Setup | ✅ Done |
| 1 | Source discovery | ✅ Done |
| 2 | PDF extraction ⚠️ checkpoint | ✅ Done |
| 3 | Cleaning (bronze → silver) | ✅ Done |
| 4 | Warehouse (gold) | ✅ Done |
| 5 | Automation | ✅ Done |
| 6 | Analytics | ✅ Done |
| 7 | Data science | ✅ Done |
| 8 | Model serving | ✅ Done |
| 9 | Backend | ✅ Done |
| 10 | LLM extraction | 🟨 Planning |
| 11 | Frontend | ⬜ Not started |
| 12 | Deploy & harden | ⬜ Not started |

Legend: ⬜ Not started · 🟨 In progress · ✅ Done

---

## Phase 0 — Setup

- [x] 1. Create monorepo structure (plan §19): `git init -b main`, `.gitignore`, top-level folders with `.gitkeep`
- [x] 2. Write `CLAUDE.md`, `PROGRESS.md`, `README.md`, `docs/adr/0001-stack-choice.md`
      (drafted 2026-11-03 ahead of Phase 0, then updated: labelled eval set rename, teaching mode)
- [x] 3. `docker-compose.yml` with PostgreSQL, RustFS, Redis, Mailpit — all four healthy and used end-to-end
      with throwaway credentials, then removed (`down -v`). Host ports 5433 and 6380 avoid OpsPilot.
- [x] 4. `.env.example` (no real secrets), including SMTP settings for Mailpit — blanks for secrets
      (compose refuses to start until filled); verified tracked by git, `.env` ignored.
- [x] 5. GitHub Actions lint workflow (Python + Java + TypeScript as each appears) — repo hygiene checks
      for now (`.github/scripts/repo-checks.sh`); first run green. Repo: https://github.com/HARITH935/drugwatch-india
- [x] 6. RustFS buckets: `raw`, `bronze`, `silver` — `docker compose run --rm rustfs-init` runs
      `infra/rustfs/create-buckets.sh` (curl SigV4, idempotent). Verified from a full `down -v` wipe.

**Done when:** `docker compose up` starts all four services; RustFS buckets exist; the Mailpit inbox is
reachable; CI passes.

---

## Phase 1 — Source discovery

- [x] 1. Locate CDSCO central and state alert pages; record URL patterns → `docs/data-sources.md` §1.
      Found two sources: the legacy PDF list on `cdsco.gov.in` (stops Jun 2025, gaps, two-hop downloads)
      and the NSQ portal on `cdscoonline.gov.in` (JSON endpoints, Jan 2019 – Sep 2026).
      Decided: portal is primary from 2019, PDFs kept (ADR 0004).
- [x] 2. Locate NPPA and Jan Aushadhi lists → `docs/data-sources.md` §2–3.
      NPPA: PDFs (compendia 2016/2022, lists to 2020, 2026 orders feed) + a 2026 Compendium dashboard with a
      browser-only CSV export; Pharma Sahi Daam's data endpoints use request signing → off-limits.
      Jan Aushadhi: SPA; product list via a JSON API that needs an anonymous guest token (not used yet).
      Policy decided in step 3 (ADR 0003). ⚠️ Still open: no bulk source for branded prices (§4.6), revisit in Phase 3/4.
- [x] 3. Check `robots.txt` and terms for each source → `docs/data-sources.md` §4.
      No site restricts automated access; CDSCO and Jan Aushadhi require permission to republish (NPPA doesn't).
      Decided: ADR 0003 (anonymous-visitor access rule + permission-first republishing),
      ADR 0004 (CDSCO portal JSON primary from 2019, PDFs kept). Email drafts in `docs/permissions.md`.
      ⏳ Harith to send the two permission emails (not blocking: needed before Phase 12 launch).
- [x] 4. Build a downloader: rate-limited, retries, skips files already in RustFS (hash check).
  - [x] 4a. Python tooling approved (ADR 0005: requests, boto3, uv, pytest, ruff). `ingestion/` uv project
        (src layout, `uv.lock`), repo-root `ruff.toml`, `python` CI job (ruff check, format check, pytest).
  - [x] 4b. Core: polite fetcher (≥3 s/host, retries with backoff, honest UA, timeouts) + RustFS store
        (hash check, metadata), with unit tests. `fetcher.py` (PoliteFetcher; stops on 403/429) +
        `store.py` (RawStore: content-addressed keys + `.meta.json` sidecar, never overwrites).
        27 unit tests (local scripted HTTP server, fake clock, fake S3) + 1 integration test passed on real
        RustFS (throwaway bucket). Layout documented in `docs/data-sources.md` §6.
  - [x] 4c. Source adapters, one at a time:
    - [x] CDSCO portal JSON (`sources/cdsco_portal.py`): month list from the portal's menus, one month per
          request, shape check (fields, row count, month) before storing, skip if stored unless `--refresh`.
          16 tests (made-up rows only: real rows aren't committed, ADR 0003). Real run: NSQ Sep-2026 (330 rows)
          + spurious Sep-2026 (1 row) stored in `raw/`; spurious field list confirmed; 5 requests.
    - [x] CDSCO legacy PDF list (`sources/cdsco_pdf.py`): reads the alerts table (stdlib `html.parser`), keeps
          44 documents (21 central NSQ, 9 state, 10 spurious, 3 combined, 1 bulk 2017-2023; matches the step-1
          inventory), alert month parsed from free-text titles and checked against the release date, two-hop
          download, `%PDF-` check. 29 tests (real title variants, fake site). Real run: June 2025 central NSQ
          (file 12927, 6 pages, 188,795 bytes) stored with ETag / Last-Modified; 3 requests.
    - [x] Jan Aushadhi product API (`sources/jan_aushadhi.py`): guest token (checked JWT-shaped, never stored) →
          whole list in one POST (the site's own export body) → completeness + field check → monthly snapshot
          `jan-aushadhi/products/<YYYY-MM>`. 13 tests (made-up token/products; token never in stored bytes).
          Real run: 2,453 products stored, no JWT-like string in `raw/`; 2 requests (+2 for a shape probe).
          Found: `mrp` = 0 for 353 products (treat as missing in Phase 3).
    - [x] Manual drop (`manual_drop.py`): stores a browser-downloaded file under `<source>/<dataset>/<period>` with
          who / when (default: file modified time) / page URL, `method = manual`; strict input checks; no network.
          16 tests. Verified on real RustFS with a throwaway bucket (no made-up file put in `raw/`).
          ⏳ First real use: Harith downloads the NPPA 2026 Compendium CSV and drops it.
    - [x] NPPA (`sources/nppa.py`): 4 listing pages, two table shapes (shared reader `sources/html_tables.py`, now
          also used by the CDSCO PDF adapter). 168 documents: 13 PDFs + 4 HTML data pages (2014 DPCO lists) + 154
          orders. nppa.gov.in's incomplete certificate chain fixed by supplying the missing intermediate (ADR 0006);
          certificate errors no longer retried. Tests: 12 NPPA + 3 table-reader + 4 fetcher. Real run: 2016
          Compendium (44-page PDF) + 30.11.2014 list (HTML) stored. Requests to nppa.gov.in: 12 (8 to study the pages,
          4 in the live run), plus 4 failed TLS attempts before the fix and 1 certificate download from Sectigo.
- [x] 5. Download the full historical archive into `raw/` with metadata (source, alert month, download time, file hash).
  - [x] 5a. CDSCO portal: every NSQ month (Jan 2019 – Sep 2026) + spurious (Jun 2025 – Sep 2026), ~118 requests.
        Done 2026-11-05 (118 requests, 7 min): 93 NSQ months = 6,956 rows; 15 spurious months = 49 rows; no empty
        months, every shape check passed. 3.5 MB in `raw/cdsco-portal/`.
  - [x] 5b. CDSCO PDFs: 44 listed documents, ~87 requests. Unlisted Aug–Dec 2024 PDFs skipped (Harith, 2026-11-05).
        Done 2026-11-05 (5 min 43 s): all 44 stored (21 central, 9 state, 10 spurious, 3 combined, 1 bulk), 251 pages,
        11.3 MB, every file a real PDF. Four 1-page files of 6–8 KB (2017-09, 2018-02, 2022-03, 2022-06): check in step 6.
  - [x] 5c. NPPA: 168 documents (13 PDFs, 4 HTML pages, 154 orders), ~170 requests.
        Done 2026-11-05 (12 min): all 168 stored (164 PDFs + 4 HTML data pages), 137 MB; orders alone 129.8 MB.
  - [x] 5d. Harith: NPPA 2026 Compendium CSV via manual drop.
        Harith downloaded the dashboard's **PDF** export on 2026-11-05 ("All Drugs Ceiling Prices", NLEM: All, 60 text
        pages); stored 2026-11-07 with `manual_drop` under `nppa/compendium-2026/2026-11` (method = manual).
  - [x] 5e. Inventory check: every file has a sidecar, hashes match, counts per source.
        `inventory.py` (9 tests; follows listing pages; exit 1 on any problem, for Airflow in Phase 5).
        Real run 2026-11-07: 321 files, 152.5 MB, every SHA-256 re-checked, no problems (8 s).
- [x] 6. Document everything in `docs/data-sources.md`: URLs, formats, layout changes over time, scanned vs text PDFs.
      §7 (2026-11-07, pdfplumber run temporarily, not added to the project): all 44 CDSCO PDFs are text (no OCR
      needed); 5 CDSCO layout families; 2017–2023 central PDFs are vaccine-only, full drug PDFs start Apr 2024, so
      Phase 2's main work is Apr 2024 – Jun 2025 (families B, C, F) with the portal as answer key. NPPA: 164 PDFs, all
      reference docs text; 9 of 154 orders unreadable without OCR (open question 11).

**Done when:** every available historical file is in RustFS with metadata, and sources are documented.

**Done-when check (2026-11-07):** sources documented ✅ (`docs/data-sources.md` §1–7). Every automatically available file
is in RustFS with a sidecar and a verified SHA-256 ✅, and the manual NPPA 2026 Compendium export is in too ✅.
Final inventory 2026-11-07: **322 files, 153.5 MB, every SHA-256 re-checked, no problems.** Phase 1 done.

---

## Phase 2 — PDF extraction ⚠️ checkpoint

- [x] 1. Classify PDFs: text-based vs scanned; layout family (central vs state, old vs new format).
      `extraction/` uv project (pdfplumber; `ingestion` as an editable path dependency for RawStore) and
      `classify.py`: family read from table header cells, `unknown` fails the run. All 44 CDSCO PDFs are text;
      families A 11 · B 19 · C 10 · D 2 · E 1 · F 1 (F = Apr 2024 spurious list, newly separated). 14 unit tests
      (self-built PDFs, no real data in git) + 1 integration test on the real archive. `docs/extraction-report.md` §1.
- [x] 2. Build pdfplumber extraction for each layout family; use Camelot where table borders are clear.
      All 6 families parse: 44 files → 1,317 rows (`docs/extraction-report.md` §2.7). Camelot not needed.
  - [x] Family B (NSQ lists 2024–2025, 19 files): `family_b.py` + `rows.py`. 1,179 rows, no serial gaps; columns
        matched by header position (handles Apr 2024's 12-column page); page-break rows merged. Portal agreement
        93.8% / 95.1%; remaining mismatches are the portal dropping leading zeros / dashes. 7 unit + 1 integration
        test. pdfplumber's ruled-table finder was enough: no Camelot needed so far.
  - [x] Shared engine `table_parser.py` (the header decides the fields; family = vocabulary). Family B moved onto it
        with identical results (1,179 rows). Shared field names (`failure_reason` for B's "NSQ Result" and C's
        "Reason for failure").
  - [x] Family C (spurious / combined 2024–2025, 10 files): 24 rows, no gaps, no unknown headers; column drift
        handled by the header; Jun 2025 matches the portal 4/4. Engine + C: 6 unit tests, 1 integration test.
  - [x] Family F (spurious Apr 2024, 1 file): 5 rows grouped by state (state rows = sections), no gaps. Vocabulary
        only. ⚠️ Spurious rows name the manufacturer printed on the fake label: never count them against it.
  - [x] Family A (vaccine lists 2017–2023, 11 files): 16 rows, no gaps; 7/7 batches from 2019 on match the portal.
        Mar 2022 starts at serial 3 (CDSCO's numbering). One overprinted cell (`2M0/s1 0B0i`) for the confidence flag.
  - [x] Family D (combined lists 2018, 2 files): 77 rows, no gaps. Combined batch/date/maker cell kept as printed
        and split at CDSCO's labels (Harith's decision): 75 split; 2 two-part packs left unsplit with a warning.
        `ParseResult.warnings` added for the confidence flag.
  - [x] Family E (bulk vaccine file): 16 rows, one year per page (`report_year`). Same 16 batches as family A plus
        status and regulatory action: Phase 3 must count each finding once. Engine: a repeated header now replaces
        the column positions (each page of E draws its columns differently); no other family changed.
- [x] 3. Handle multi-page tables, merged cells, and multi-line product names.
      Done inside the step-2 engine and tested: page-break continuations merged (`test_merges_a_row_cut_by_a_page_break`),
      split / merged cells aligned by header position (B Apr 2024, C Jun 2025), multi-line text kept with line breaks.
- [x] 4. Attach provenance to each row: source file, page, row index.
      `extract.py`: `extract_pdf(raw key)` checks the bytes against the sidecar SHA-256, classifies, parses, and stamps
      every record with source key + SHA-256, CDSCO source URL, dataset, alert month, file id, listing title, family,
      page(s), row index, section, `extraction_method = rule`, extractor version, warnings. 44 PDFs → 1,317 records,
      all with full provenance. 3 unit + 1 integration test.
- [x] 5. Assign a confidence flag per row (all required fields present and well-formed = high).
      `confidence.py`: high = required fields present and well-formed + no parser warning; low lists every reason
      (`missing`, `not stated`, `not a date`, `Excel day number`, `several values`, `parser warning`, ...).
      **1,214 high (92.2%), 103 low**; only 3 low rows are parser problems, the other 100 are what the PDF prints.
      Engine now warns on overprinted cells (the Feb 2018 one). Found and fixed a step-2 gap: B Apr 2024's
      `Mfg Dt` / `Exp Dt` headers (17 rows' dates were in `other_*`); the archive test now fails on any unknown header.
      Tests: 35 confidence unit tests, 2 overprint + 1 B-header unit tests, archive counts in the integration test.
- [x] 6. Write rows to `bronze/` as Parquet.
      pyarrow approved (ADR 0007). `bronze.py`: one file per source PDF next to its `raw/` key, one 37-column schema
      for every family (null = no such column, `""` = blank cell; unknown headers in an `extra_fields` map; unexpected
      fields refused). **44 files, 1,317 rows, 759 KB**, read back from RustFS with identical schema. Fixed an exit-time
      hang in Arrow's thread pools on macOS by reading single-threaded from an Arrow buffer (0 pool threads; 4/4 runs
      exit). Portal JSON → bronze is a separate later step (Harith's choice). Tests: 7 unit + 1 integration.
- [x] 7. Create a **labelled eval set**: ~300 rows labelled by hand, sampled across months and layouts.
  - [x] Labelling kit (2026-11-10): `eval_set.py` draws the sample (up to 12 random rows per PDF, seed 2026: **309 rows**,
        all 44 PDFs, 28 months, 6 families) and fixes the split by whole PDF (train 187 / validation 53 / test 69) in
        `extraction/eval/manifest.csv` (row IDs only; refuses to be overwritten). `label.py`: terminal tool that opens the
        page picture with the row outlined, asks field by field (Enter / text / `/b` / `/u` / `/q`), saves each row at
        once, resumes, `--redo N`. Guide: `docs/eval-set.md`. Tests: 8 + 5 unit, 1 integration (manifest reproducible).
  - [x] First hand-labelling attempt set aside (2026-11-11): 64 of 72 rows were saved within 7 s (repeated Enter /
        keys typed before the question appeared), so not really checked. Tool fixed: typed-ahead keys are discarded,
        a row answered in under 8 s is asked again (proven in a pseudo-terminal).
  - [ ] AI-assisted labels (Harith's decision): `second_reader.py` renders one picture per row; Claude reads each
        without seeing the parser's values; agreeing values become labels, disagreements go to Harith
        (`label --review`). Pilot rows 1–10: 59 of 60 values agree; the 1 disagreement is the parser's overprint error.
        All 309 read (2026-11-12): 1,837 of 1,849 values agree, 300 rows labelled; 12 values in 9 rows wait for Harith
        (`label --review`). Row 249: the second reader "corrected" a CDSCO typo (`Absortion`); the comparison caught it.
  - [x] Harith decided all 12 disagreeing values (2026-11-12): **309 of 309 rows labelled**. Consistency check: rows
        18 and 210–212 had been decided differently from identical cases (rows 178, 213); with Harith's approval Claude
        aligned them (recorded in each label as `decided_note`). Labels backed up to Harith's iCloud Drive.
- [x] 8. Measure rule-based parser accuracy against the labelled eval set (field-level precision/recall/F1).
      `evaluate.py`: **baseline F1 99.6%** (P 99.7%, R 99.5%; 1,846 values). Test split 99.5%; low-confidence rows in
      the test split 92.3% (only 6 rows: thin for Phase 10). All 9 errors known: two-part pack (4), overprint (1),
      stray serial dot (4, flagged high: the confidence flag misses it). Extraction report §3.1. Regression test guards
      the baseline. 8 unit + 1 integration test.

**Done when:** parser runs across the whole archive and baseline F1 is recorded.
**Checkpoint decision:** if extraction quality is too low or PDFs are mostly scanned images, re-scope here.

**Phase 2 Done-when check (2026-11-12):** ✅ the parser runs across the whole archive (44 PDFs → 1,317 records →
44 bronze Parquet files); ✅ baseline F1 recorded (99.6%, extraction report §3.1). Checkpoint: quality is high and no
PDF is scanned, so no re-scope. **Phase 2 closed with Harith's approval, 2026-11-12.**

---

## Phase 3 — Cleaning (bronze → silver)

Approved 2026-11-12. Plan: `DRUGWATCH_PHASES.md` §9 Phase 3.

- [x] 0. Portal JSON → bronze (carried over from Phase 2 step 6, Harith's choice): one Parquet file per downloaded
      month, cp1252-decoded, shared field names, `extraction_method = api`, provenance without page numbers.
      `portal_bronze.py`: **108 months → 7,005 rows** (6,956 NSQ + 49 spurious), read back with identical schema, 3 s.
      Strict cp1252 worked everywhere; no unexpected portal fields. If a month is downloaded twice, only the newest
      response is in bronze. A test caught a real bug first (a sidecar key was accepted as a response key). Mapping:
      `docs/data-sources.md` §1b; ADR 0004 update. Tests: 8 unit + 1 integration.
- [x] 1. PySpark job reads bronze Parquet.
      New `spark/` uv project; PySpark 4.2.1 pinned below 4.3 (its Hadoop version can move). Spark reads RustFS
      directly via Hadoop's S3A connector (`hadoop-aws:3.5.0` + AWS SDK bundle, ADR 0008, Harith's choice).
      `read_bronze.py` reads a whole bronze folder (recursive, non-partitioned) as one table. **Confirmed against
      real RustFS: 1,317 PDF rows (44 files, same family split as Phase 2) and 7,005 portal rows (108 files, same
      split as step 0)**, both with the expected column counts. A test fails if Spark's own Hadoop version ever
      stops matching the connector. `prefetch.py`: a resumable, checksum-verified downloader for the 686 MB SDK
      jar, written after a single-stream download kept failing on a slow connection; it primes Maven's local cache
      so Spark's own resolver finds it there instead of re-downloading (confirmed: `found ... in local-m2-cache`).
      Fixed one bug a test didn't yet cover: `RUSTFS_ENDPOINT` defaulting differently here than in
      `RawStore.from_env()` (both now default to `http://localhost:9000`, matching `.env`, which never sets it).
      CI installs Java 17 explicitly for `spark/` (`lint.yml`), rather than trusting the runner's default JDK.
      Tests: 10 unit + 1 integration (prefetch's pieces/resume/checksum logic, S3A config, the real lake read).
- [ ] 2. Normalize text: case, whitespace, punctuation, common abbreviations ("Ltd." → "Limited").
  - [x] Whitespace (2026-11-12): `clean_text.normalize_whitespace()` collapses runs of spaces/tabs,
        strips each line's own edges and the whole value's outer edges, and turns non-breaking spaces
        into regular ones - while deliberately keeping line breaks, including meaningful blank-line
        separators (one portal `manufacturer` field states the maker, then a blank line, then the
        separate marketer). Checked against real bronze: **PDF rows were already clean (0 changes,
        confirming Phase 2's own line-joining); portal rows had 1,533 values fixed** across 9 fields
        (`failure_reason` 831, `manufacturer` 368, `generic_name` 225, `reported_by` 72, ...).
        Letter-spacing ("A s s a y") deliberately deferred: real examples mix spaced and normal text
        on one line and are not always one character per gap, so a blind regex risks corrupting real
        text; it needs its own careful, separately-tested pass. Case and abbreviation expansion
        ("Ltd." -> "Limited") not started. Tests: 9 unit (clean_text.py; grounded in the real quirks
        found above), plus clean_bronze.py as a read-only report script (nothing written to silver/
        yet: later steps still need to run first).
  - [x] **Found and fixed** (2026-11-12, Harith's decision): 9 of 7,005 portal NSQ rows (alert month
        2019-01) had a **wrong `batch_no`** - the portal's own field was stale (reused from an earlier
        row) or had a stray trailing comma, while the TRUE batch number, manufacturing date, expiry
        date and manufacturer were sitting correctly inside the `manufacturer` field as one combined
        cell (`"B. No.: X,\nMfg dt: Y, Exp dt: Z, Mfd by: W"`) - the exact format Phase 2's family_d.py
        already parses for the 2018 PDFs. Likely a CDSCO portal backend bug for this one batch of
        historical rows, not anything in our pipeline.
        `fix_portal_batch.py` reimplements family_d's split-by-labels rule (not imported, so Spark jobs
        don't pull in pdfplumber for one small pure-text function) and overwrites batch_no/mfg_date/
        expiry_date/manufacturer wherever the pattern matches - the trigger is the pattern itself, not
        a hardcoded list of 9 rows, so it also catches a recurrence elsewhere. **Verified against real
        data: all 9 rows corrected** (e.g. a row the portal had wrongly stamped `8S17004,` now reads its
        real batch `PT-180905`). A second bug found along the way and fixed too: one row's source text
        has a stray double comma (`"08/2018,               , Exp dt:"`); the original single
        `removesuffix(",")` logic (inherited from family_d.py) left one comma behind, so this module
        uses `strip(" \t\n,")` instead, which removes a whole run in one pass. **Checked and confirmed
        this doesn't affect Phase 2's shipped, closed PDF work**: all 77 real family-D PDF rows have
        zero trailing-comma leftovers, so family_d.py itself is untouched. Tests: 10 unit (including the
        real PT-180905 and double-comma cases).
- [ ] 3. Parse dates from all observed formats; validate mfg date < expiry date.
  - [x] Portal dates (2026-11-12): `parse_dates.parse_portal_dates()`. Checked first, before writing
        code: portal `mfg_date`/`expiry_date` are **one shape in 100% of ~13,780 real values**
        (`"Mon-YYYY"`, e.g. `"Aug-2017"`); PDF dates are not (30-40 shapes - 2-digit vs 4-digit years,
        `DD-MM-YYYY`, letter-spaced, split across a line break, Excel day numbers, textual expiry
        rules like "5 Yrs from the date of Mfg."), several overlapping the letter-spacing problem
        already deferred in step 2. Scoped to **portal only** for this slice; PDF dates need their own
        careful, separately-evidenced pass.
        Adds `mfg_date_parsed`/`expiry_date_parsed` (real dates; the original text columns are kept,
        not overwritten) and `dates_valid` (true/false/null - null when a date is missing or didn't
        parse, never guessed). **Verified against all real portal rows: 6,892/6,892 and 6,889/6,889
        present values parsed (100%).** Found, not fixed (the plan says *validate*, not correct): **16
        of 6,876 rows have mfg_date on or after expiry_date** - a real CDSCO/portal data issue, e.g. a
        manufacturing date a full year after its own expiry date.
        Found before shipping: Spark 4's `to_date()` is strict (ANSI mode) and **crashes the whole job**
        on the first unparseable value instead of returning null; switched to `try_to_date()`. Tests: 6
        unit (a real parse, the original text kept, the real mfg>=expiry examples, null-safety, case).
  - [x] PDF dates, part 1 (2026-11-12): `parse_pdf_dates.parse_pdf_dates()`. Added only the formats
        proven both common and **unambiguous one at a time against every real value** - never a guess:
        `MM/yyyy`, `MM/yy`, `MMM-yy`, `MMM-yyyy` (all checked zero cross-matches with each other), and
        `dd-MM-yyyy` (proven day-first: 17 real values have a first number over 12, impossible for a
        month; zero have a second number over 12, which would have proven month-first). **Covers 88.8%
        / 88.6% of present mfg_date / expiry_date values**, zero ambiguity. Left for a separately-
        evidenced follow-up: `DD.MM.YYYY` (ordering not yet checked), Excel day numbers, textual
        expiry rules, letter-spaced/line-broken dates, placeholders.
        Found a real row the validity flag is meant to catch: `"Bisacodyl Tablets Ip 5mg"` prints
        `Jun-42` as its mfg date against a `2026` expiry - a CDSCO typo (manufactured 16 years after
        its own expiry). Parsed exactly as printed, correctly flagged `dates_valid = false`; **not**
        silently "corrected" (this is the same row from the eval-set labelling work, so it was already
        known to be a genuine source typo, not a parser error).
        **A second, more serious bug found by checking actual results, not assumed:** Java's lenient
        parser does not just fail on a malformed value - `try_to_date("Apr--2026", "MMM-yyyy")`
        "succeeds", reading the doubled dash as a **sign on the year** and returning year **-2026**
        (2027 BC), a date so extreme that even converting it to a Python date **crashes**. Fixed with
        `plausible_year()`: any parsed date outside confidence.py's own 1990-2049 range for this
        archive becomes null instead. Applied to **both** date modules (portal included, even though
        no real portal value has triggered it) for consistent safety; the mutation check (temporarily
        disabling it) confirmed both regression tests catch it. Re-verified against real data after
        the fix: exactly one corrupted parse removed (expiry_date 88.6% -> 88.5%), nothing else moved.
        Tests: 5 unit (one per format, the real Bisacodyl row, an ordinary valid row, the real
        double-dash crash, deferred formats staying null).
- [ ] 4. Split product name into brand, generic/salt, strength, dosage form.
      Plan agreed with Harith (2026-11-13): three pieces, easiest first, because product names are
      far messier than dates (brand-first vs generic-first, no reliable separator, combination drugs
      with several strengths, the step-2 letter-spacing problem, and the portal's `generic_name`
      sometimes holding the brand while `brand_name` says "NA"). 1. dosage form, 2. strength (kept as
      a list), 3. brand vs generic only where the pattern is clear (null otherwise; the rest is what
      Phase 10's LLM fallback is for).
  - [x] Piece 1, dosage form (2026-11-13): `dosage_form.add_dosage_form()`. Every rule checked against
        all 8,322 real names first: a fixed vocabulary of form words (whole words, any case); short
        abbreviations (Tab, Caps, Inj.) proven safe (all 101 abbreviation-only matches genuine), but
        ignored right after a hyphen (`"NS-CAP"` is a brand, not a capsule); several forms -> null,
        except **Injection wins** (all 62 distinct real names of that kind are injections: "Solution
        for Injection", "Powder for Injection"...). "Sachet" (packaging) and "Respules"/"Rotacaps"
        (device brands) left out of the vocabulary on purpose; "Bolus" (veterinary) added. Adds
        `dosage_form` and `dosage_forms_found` (so every null can be explained).
        **Verified on real data: 7,402 of 8,322 names filled (88.9%)**: PDF 86.5%, portal 89.4%.
        Left null on purpose: 60 mixes with no checked rule (e.g. "Ophthalmic Solution (Eye Drops)")
        and 860 names with no form word (mostly correct: vaccines, syringes, cotton, sanitizers; a
        few CDSCO typos like "Tables", "Caspules", "TabletsIP" not guessed). Tests: 17 unit; a mutation
        check (removing the hyphen guard, then the Injection rule) made exactly the matching test fail.
  - [x] Piece 2, strength (2026-11-13): `strength.add_strengths()` -> `strengths`, a list. Every rule
        checked against all 8,322 real names first. Units: mg, mcg, g/gm, ml, IU, % (+ w/v, w/w,
        v/v); "cm" (dressings) and "billion" (4 probiotic rows) left out. A slash is "per" only before
        a volume or "per gram" (`125 mg/5 ml`, `10 mg/ml`, `60000 IU/g`); otherwise it joins two
        strengths of a combination (`40mg/12.5mg` = 40 mg + 12.5 mg; 43 real names). Skipped on
        purpose: a bare `N ml` (all 433 real ones are bottle sizes), a bare `N g` outside injections
        (tube/soap/cotton sizes, a needle gauge "23G", a brand "3G", a typo "Tablets 200 g"; costs 2
        real gram strengths), and a number glued to a letter (16 real cases; `"VitaminD3250 IU"` is
        D3 + 250 IU, not 3,250 IU). **Every mention kept in printed order, repeats included**: most
        repeats are the brand echoing the strength, but some are real combinations sharing a value
        (`Amoxycillin 250 mg and Cloxacillin 250 mg`), and removing repeats would lose an ingredient.
        Written one standard way (`1.0 gm` -> `1 g`, `0.50%` -> `0.5%`, `60,000 IU` -> `60000 IU`).
        **Verified on real data: 3,165 of 8,322 names (38.0%) have a strength** (PDF 35.8%, portal
        38.5%); the rest print none with a unit (brand numbers like "Telzasig 20" are not guessed).
        Tests: 28 unit; a mutation check of the four main rules (bare ml, gram only for injections,
        glued numbers, slash = "per") made exactly the matching test fail each time.
  - [x] Piece 3, brand vs generic (2026-11-13, the hardest piece, on purpose last): `brand_generic
        .split_brand_generic()` -> `split_brand_name`/`split_generic_name`. Real names have no
        reliable order (brand first or generic first, both happen) and often no separator at all,
        so this only splits where the SHAPE itself proves which side is which, in two stages, then
        two rounds of sanity-checking the real result rather than assuming it was safe:
        1. **Shape**: exactly one top-level bracket group (nested brackets count as one; 50% of
           PDF names, 36% of portal NSQ names qualify). Zero groups, 2+ groups, unbalanced
           brackets (a cut-off cell) all stay null.
        2. **Side**: the side WITH an official pharmacopoeia marker (IP/BP/USP, any dotted form) is
           the generic, the other is the brand - a brand name essentially never carries one (only
           1.9% ambiguous, vs 29.5% for a dosage-form-word signal tried first and rejected for
           being too often ambiguous). Both/neither -> null.
        3. **Sanity checks on the real result** (not assumed safe in advance): a bare-marker
           generic with nothing else (1 case: "ABSORBENT COTTON WOOL (IP)"); a "brand" that was
           really just the strength (52 of 1,860 splits, 2.8%: "(100mg/1.5mg)"), caught by reusing
           `strength.py`'s own STRENGTH pattern rather than a second, weaker one; and "Ringer
           Lactate Solution for Injection" (29 occurrences, 5 spellings) - a second, synonym
           description of the same composition, not a brand, caught because a real brand is never
           named **for** its own route of administration - checked against all 62 real multi-word
           candidates: only those 5 spellings rejected, every genuine one ("DOLOSAFE D TABLETS")
           kept even though it also ends in a dosage-form word.
        **Verified on real data: 356 of 1,317 PDF names (27.0%), 1,389 of 7,005 portal rows
        (19.8%) split.** Named `split_*`, not `brand_name`/`generic_name`: portal NSQ rows already
        have their own `brand_name` bronze column (13.8% real, rest placeholder); overwriting it
        would silently discard real portal values, so reconciling the two is left to the gold
        layer. **Known residual, documented rather than chased further**: a handful of scattered
        cases ("NOT STERILISED", "VET") pass every check but aren't really brand names - rare and
        unconcentrated, unlike the Ringer Lactate case, so not worth a further rule here. Tests: 16
        unit; a mutation check of all 4 guards (shape, bare-marker, strength, route) made exactly
        the matching test fail each time.
- [ ] 5. **Manufacturer entity resolution** with RapidFuzz: cluster spelling variants into one canonical manufacturer;
      keep a reviewed mapping table.
      Plan agreed with Harith (2026-11-13): piece 1 cleans the name (strip the address, expand
      abbreviations); piece 2 finds look-alikes with RapidFuzz; piece 3 is Harith's own review of
      the borderline pairs, same as the eval-set labelling - a missed merge is better than a wrong
      merge (CLAUDE.md Section 5). This is also where step 2's deferred case/abbreviation work and
      step 4 piece 3's brand/generic split actually pay off.
  - [x] Piece 1, clean the name (2026-11-13): `manufacturer_name.clean_manufacturer_name()` ->
        `manufacturer_name`/`manufacturer_address`. The `manufacturer` field holds the company name
        AND its full postal address in one string. Checked against all 8,271 real values first:
        - Boundary: the first comma (97.4% of values have one); where there is no comma but a
          legal suffix (Pvt. Ltd., Limited, LLP) is found, its end is the boundary instead.
        - `"(A Unit of ...)"`/`"(A Division of ...)"`/`"(A Subsidiary of ...)"` right after that
          boundary is identifying information, not address (49 real occurrences, 2 real companies);
          the real boundary is pushed to the next comma, past that aside.
        - **74 of 8,271 values (0.9%) have neither a comma nor a legal suffix anywhere** - no
          reliable signal to cut on. Left whole (name = full text, address = null) rather than
          guessed; a few of these are also letter-spaced, the same problem deferred in step 2.
        - Placeholders (`"Spurious"`, `"Not applicable"`, `"Under Investigation"`, ...) -> both
          null. The portal spurious tab's own manufacturer is the name on a **fake** pack
          (CLAUDE.md Section 6) and in the real data is **always** exactly `"Under Investigation"`
          anyway, so this rule already keeps it out without any special-casing.
        `M/s.` stripped (4 real spacing/punctuation variants); `Pvt.`/`Ltd.` spelled out. **Case
        left exactly as printed, not title-cased**: real names mix ALL CAPS with mixed case, and
        some ALL CAPS names are genuine acronyms (`"JKMSCL"`) that title-casing would turn into
        `"Jkmscl"` - worse to read and unnecessary, since piece 2's RapidFuzz call can compare
        case-insensitively on its own.
        **Found and fixed before shipping**: the same regex bug as `brand_generic.py`'s PHARMA
        pattern - `\bLtd\.?\b` matches only `"Ltd"` (not its own period) when a non-word character
        immediately follows, because `\b` needs a transition and `.` next to a comma is non-word
        on both sides. Fixed with `(?!\w)` instead of the trailing `\b`, everywhere a pattern ends
        in an optional period.
        **Verified on real data: 94.8% of PDF values, 97.8% of portal values split into a name and
        address.** Tests: 10 unit; a mutation check of all 4 rules (ownership aside, suffix
        fallback, placeholder, `M/s.` stripping) made exactly the matching test fail each time.
  - [x] Piece 2, cluster the variants (2026-11-13): `manufacturer_cluster.cluster_variants()` ->
        `manufacturer_canonical`. RapidFuzz (approved stack, Section 6) `token_sort_ratio` with its
        own `default_process`, so case and `Private.Limited` vs `Private Limited` cost nothing.
        **Threshold 98, picked by reading real pairs in every band, not by feel:**
        - 98-100 (189 pairs): every sampled pair was the same company - plural/singular, punctuation,
          case, OCR noise (`Relief`/`Relif`, `Healer's`/`Healer?s`), stray page numbers.
        - 95-98 (260 pairs): **mixed** - real matches (`UPKAR PHARMACEUTIALS`) sit next to clear
          false ones (`RPL (INDIA) Pharmaceuticals Private Limited` vs `ZRS Pharmaceuticals India
          Private Limited` scores 95.1 but is two different companies).
        - 92 and below: mostly false - different companies share the generic tail, so `Sarv`/`Solar`
          and `PRS`/`Pulse` both score 92+.
        So 98+ merges automatically, 95-98 goes to piece 3's human review, below 95 neither.
        `token_set_ratio` was rejected: it ignores extra words, so `Nest Healthcare` and `Nest
        Healthcare Plot No.: 300` would score 100 and might be two units of one company.
        Clusters by connected components (union-find), since similarity isn't transitive; checked
        every real cluster of 3+ for bad chaining - all coherent (8 spellings of `J.M. Laboratories`,
        8 of `Martin & Brown Bio-Sciences Private Limited`). Conservative on purpose: 3 separate
        Martin & Brown clusters stay apart (one carries a leftover address fragment), which is what
        piece 3 is for. Canonical = most rows, then not ALL CAPS/all lower-case, then alphabetical
        (top count is tied in 126 of 436 clusters; the casing rule decides 6, always readably).
        **Two bugs found by reading real output, not assumed safe:**
        1. `dtype=np.uint8` (chosen to save memory) **rounds** - it silently auto-merged 34 real
           pairs scoring 97.5-98, skipping the review they are meant to get. Most happened to be
           genuine, which is luck, not a guarantee.
        2. Fixing that led to a better design: `process.extract` with a `score_cutoff` instead of
           `process.cdist`. **Identical results** (same 818 pairs at 98+, verified), ~6 s instead of
           3 s, keeps only the pairs above the cutoff instead of a 44 MB n x n matrix - and **drops
           the numpy dependency entirely**, so no new library needed approval.
        **Verified on real data: 3,320 distinct names -> 2,734 manufacturers, merging 586 spelling
        variants; 260 pairs queued for piece 3.** Tests: 10 unit; a mutation check of all 6 rules
        (threshold, review floor, both canonical rules, transitive join, band ceiling) made exactly
        the matching test fail each time.
  - [x] Piece 3, the review tool (2026-11-13): `manufacturer_review.py`. Sorts the 260 borderline
        pairs by **what actually differs**, checked against all of them:
        - **spacing (13)**: only spaces/punctuation move (`Pharma Roots`/`Pharmaroots`) - no letter
          changes, safe as a batch;
        - **common-word typo (87)**: every differing word is a misspelling of a word used across
          many DIFFERENT companies (`Pharmaceuticlas`->`Pharmaceuticals`, `&`->`and`, `Hidustan
          Antibitics`->`Hindustan Antibiotics`) - one spelling is a real word, the other is not;
        - **judgement (160)**: the difference touches the **distinctive** part of the name, where a
          typo and a second real company look identical (`Agron`/`Argon`, `Sai`/`Sia`,
          `Dexbio`/`Dexibo`). Asked one at a time; never decided automatically.
        A word counts as "common" only at 3+ letters: `(S)` reduces to the token `s`, which is all
        over the archive, so a length-blind rule called `Shell Eastern Chemicals` and `Shell
        Eastern Chemicals (S)` typos of each other when `(S)` is likely a separate legal entity.
        Judgement pairs are asked **most-obviously-a-typo first** (a one-letter slip in a long word
        scores 0.95; a whole extra token like `... Limited II`, possibly a second plant, scores
        0.00), so the calls needing thought come last instead of being buried mid-list.
        **Deliberately NOT grouped**: asking once per connected cluster would be fewer questions but
        chains different companies together - `Apple`/`Apex`/`APT Formulations` land in one group,
        as do `Spen`/`Super Formulations`, and one "yes" would merge all three. Found by checking,
        before building the tool around grouping.
        Decisions append to git-ignored `data/manufacturer-review/decisions.jsonl` as each is made
        (stop and resume any time; a later answer replaces an earlier one), with the same safety
        nets as the eval-set labeller: keystrokes typed before a question appears are discarded, an
        answer faster than 2 s is asked again, an unknown key is not taken as an answer, and Ctrl-D
        stops quietly instead of printing a traceback over already-saved work.
        Tests: 21 unit. A first mutation run found **three tests too weak to prove their own claim**
        (the `(S)` guard, the unknown-key guard and the asking order); all three were strengthened
        until the mutation failed them.
        **Run for real and COMPLETED by Harith (2026-11-18): all 260 pairs decided - 13 spacing + 87
        common-word typo accepted as batches, and the 160 judgement calls answered one at a time:
        95 merged, 65 kept apart.** Rejecting 41% of the judgement pairs is the round working as intended:
        those are the pairs where a typo and a second real company look identical.
        **Verified end to end: 195 merges applied, 2,720 -> 2,609 distinct manufacturers.**
  - [x] Piece 4, make the decisions count (2026-11-18). **Found before Harith spent an hour reviewing: nothing
        read the decisions.** Piece 3 wrote `decisions.jsonl` and exposed `merges_from_decisions()`, but
        `cluster_variants()` had no parameter for accepted pairs and neither pipeline imported it - so 260
        answers would have produced byte-identical silver. Now `cluster_variants(counts, merges=...)` adds each
        reviewed pair as a union-find edge whatever it scored, and `build_silver` and `pandas_pipeline` both pass
        `merges_from_decisions()` in, so the two engines stay in step.
        Only "same company" answers are used: a rejected pair needs no handling, because the review band is
        95-98, below the 98 auto-merge threshold, so "not the same" is already what happens. A decision naming a
        name that no longer exists (a cleaning rule changed since) is **skipped, not guessed at**. The report now
        prints `merges accepted by review: N`, so a review's effect is visible rather than taken on trust.
        **Verified on the real archive with no decisions file: 7,128 rows, 2,720 manufacturers, 0 reviewed
        merges - identical to before, so the wiring is inert until someone reviews** (which is also what CI and
        a fresh clone see). Tests: 8 new (6 clustering + 2 pipeline). A mutation check of both halves (not
        passing the decisions in; dropping the reviewed edges) failed exactly the matching tests.
        **What the review is worth, measured (read-only preview, no decisions made):** 3,302 distinct cleaned
        names → 2,720 manufacturers today; accepting the 100 mechanical pairs would give **2,670** (50 merges),
        and accepting all 160 judgement calls too would give at most **2,587** (133 merges).
- [x] 5b. **The cleaning pipeline: bronze -> silver** (2026-11-13). Until now every cleaning step was its own
      module printing its own report and nothing ran them together. `build_silver.py` is the job that does, and
      the Parquet it writes is Phase 3's silver deliverable (what step 8's GE suite validates, what Phase 4's dbt
      loads, and the "cleaning job" step 9 benchmarks). Each source gets the steps that suit it (PDF: the 5 proven
      date formats; portal: the 9 wrong batch numbers, then dates), then both are mapped onto **one 30-column
      silver schema** with the raw value kept beside every cleaned one. Manufacturer clustering runs **last and
      across both sources at once**, so one company spelled differently in a PDF and in the portal becomes one
      manufacturer.
      **Verified on the real archive: 1,317 + 7,005 = 8,322 silver rows** (row counts unchanged by the pipeline -
      a duplicate key in the clustering lookup would silently multiply them), written to `s3a://silver/nsq/`
      partitioned by source and alert month, and read back at 8,322. mfg_date 96.7% / expiry 96.6% / dosage_form
      88.9% / a strength 38.0% / brand-generic split 21.0% / manufacturer named 98.4%; **2,723 manufacturers**
      (2,734 standalone, because spurious names are correctly excluded here). The remaining 146 unparsed dates are
      exactly the formats step 3 deferred on purpose (`NIL`, `Not Mentioned`, Excel day numbers, `29.09.2021`,
      `5/2023`, line-broken) - no regression.
      **The spurious rule (CLAUDE.md Section 6) enforced in code:** a spurious alert names the company printed on
      a FAKE pack. Real data holds three kinds - `"Under Investigation"`, a firm CDSCO says does not exist, and
      **17 rows naming real, legitimate companies whose identity was counterfeited** (Ipca, Macleods, Sun Pharma,
      Glenmark, Emcure...). So on a spurious row the text is kept as `name_on_pack` for provenance and every
      manufacturer column is NULL. **Verified: 77 spurious rows, 0 attributed to any manufacturer.**
      **Two real defects found by reading the composed output, not assumed safe:**
      1. `fix_portal_batch` overwrites `batch_no`/`mfg_date`/`expiry_date`/`manufacturer` **in place**, and the
         `_raw` columns were being built from those already-corrected columns - so silver promised provenance it
         did not have, exactly where a reader would check it. Fixed with `keep_raw()`, a snapshot taken before any
         step runs. Verified on real rows: the stale/comma'd originals the portal published (`"HC-834"` ->
         `"AHB-3086"`, `"AHT-1239,"` -> `"AHT-1239"`) are now visible beside the correction.
      2. The same fix replaces those rows' dates with the text out of CDSCO's combined cell, which is written the
         **PDF** way (`"03/2018"`), not the portal's `"Mon-YYYY"` - and `parse_portal_dates` was proven against
         bronze, before the fix. **All 9 rows silently lost both dates and `dates_valid`.** Fixed by falling back
         to `parse_pdf_dates`' 5 already-proven formats for whatever the portal format can't read, with
         `dates_valid` recomputed from what survives. Verified: mfg 8,038 -> 8,047 and expiry 8,031 -> 8,040,
         exactly +9, nothing else moved; the cell's dates agree with the portal's own where both exist.
      Tests: 16 unit (13 carried over, 3 new). A mutation check of both fixes (taking the snapshot late; dropping
      the fallback) made exactly the matching test fail each time.
      **Left for step 7** (the first of these is now done - step 7 dropped the bulk file): `alert_month` is NULL
      on the **16 `nsq-bulk` rows** (CDSCO's bulk
      2017-2023 file prints one year per page, so there is no single alert month) - they are the same 16 findings
      family A already reports monthly, so dedup drops them and the nulls with them. And `is_spurious` is read
      from `source_dataset`, CDSCO's **document-level** category: **78 rows sit in "combined NSQ/spurious"
      documents**. Checked - all 78 come from the NSQ-shaped table and every failure reason is a lab test, so
      none is a counterfeit report and today's data is right; but a future combined document with a spurious
      section would be attributed silently. ⏳ **Harith's call: add a row-level spurious signal, or keep the
      document-level rule and document it?**
- [x] 6. Map failure reasons into standard categories (2026-11-13). `failure_category.py` ->
      `failure_categories`, joined into `build_silver`'s pipeline (not another standalone report).
      **Checked the real values before designing anything:** `failure_reason` is free text written by whichever
      government lab tested the sample - **3,730 distinct values** over 8,317 rows once case and line breaks are
      normalised, from a bare `"Dissolution"` to 994-character sentences, and the 800 most common cover only
      **61.5%** of rows. So a value->category lookup table cannot work; the category is read from the text.
      **Three decisions Harith made on that evidence (ADR 0009):**
      1. **A list, not one value per row** - 1,833 rows (22.0%) name more than one failed test
         (`"Dissolution and Assay"`, `"ph, particulate matter and description"`, up to seven in one row). An array,
         like `strengths`, so nothing is silently dropped by a priority rule that is hard to defend.
      2. **A wider vocabulary than the plan's 7** - those 7 left **17.5%** of rows in "Other", and that residue was
         not noise: every pH, Content, Related Substances, Uniformity, Water, Identification and Disintegration
         failure sat in it. "Other" would have been the second-largest slice on a dashboard. 14 test categories +
         Spurious + Other brings **Other down to 3.1%** (255 rows).
      3. **"Content" counts as Assay** - an assay IS a content determination and CDSCO writes both for the same
         finding; but `water content`, `moisture content` and `uniformity of content` are other tests, excluded by
         name.
      **Spurious comes from `is_spurious`, never from the word** (CLAUDE.md Section 6): one real NSQ row ends
      `"...the tests for identification and assay spurious"`, and the word appears in **264** rows' text when only
      **77** are spurious reports. A spurious row still keeps its lab-test categories - those tests were really
      run, on the seized counterfeit sample.
      **The false positive that mattered, found by auditing what each pattern actually matched rather than trusting
      the coverage number:** in this archive "label" usually means the *declared strength*, not the printed label.
      `"does not conform to label claim with respect to the content of ketoconazole"` (105 rows), `"...34.85% of
      the labelled amount"` (42), `"conform to label with respect to the content of..."`, `"against labelled claim
      of 2500 mg"` - all strength shortfalls, already counted under Assay. A bare `\blabel` reported **390
      labelling offences against the 287 the allow-list finds: 103 rows (26%) were strength shortfalls recorded as
      labelling offences.** Carving out each phrasing one at a time only moved the goalposts, so the rule was
      inverted into an **allow-list** of what CDSCO actually writes for a labelling offence. Mislabelling is an
      accusation, so this category is conservative the same way manufacturer merging is: a missed category beats a
      wrong accusation.
      Also: `misbranded` is **Labelling, not Spurious** (filing it under Spurious would accuse a maker of
      counterfeiting); `Disintegration` is its own category (different test from Dissolution, 303 rows alone);
      every pattern is bounded, because `bet` (the Bacterial Endotoxin Test) would otherwise match "diabetes" and
      "betamethasone", and `ph` would match "graph" and "morphine"; CDSCO's own misspellings are matched **as
      spelled** (`misbrandad` 13, `sterillity` 6, `alochol` 6, `susbtances` 3, `uniformaly` 3, `appeareance` 2) -
      a typo in the source is not a reason to lose the row's category. A reason naming no test (`"nsq"`,
      `"not applicable"`, `"does not conform to i.p."`) gets `Other`; **no reason at all gets an empty list**,
      which is a different fact and stays distinguishable.
      Fixed before shipping: the module docstring was not a raw string, so the `\b` in its examples was a real
      backspace character (and `\w` raised a SyntaxWarning).
      **Verified on the real archive:** silver rebuilt with the column and read back at **8,322 rows, now 31
      columns**, `failure_categories` typed `array<string>`. Spread: Assay 40.4% (3,365) · Dissolution 26.9%
      (2,238) · Description 16.0% (1,333) · Sterility 6.9% · Particulate 6.4% · Identification 5.6% · pH 4.4% ·
      Disintegration 3.6% · Uniformity 3.6% · Labelling 3.4% · Other 3.1% · Physical 2.9% · Related substances
      2.8% · Water 1.9% · Spurious 0.9%. **No row comes out with zero categories**, which also cross-checks:
      the only 5 rows with no reason text are the 5 reason-less rows in the spurious documents, so they come out
      as `["Spurious"]` alone.
      Tests: 49 unit, every reason text a real archive value.
      The measured distribution is in **ADR 0009**; the user-facing version belongs in
      `docs/methodology.md` when that page is written (Phase 11/12). Step 8's GE suite should assert every value is
      in this vocabulary and watch the "Other" share, which is how a change in CDSCO's wording will show up.
- [x] 7. Deduplicate repeated rows (2026-11-14). `deduplicate.py`, joined onto the end of `build_silver`'s
      pipeline (its key needs `manufacturer_canonical`, so it must run after the clustering). ADR 0010.
      **The plan's premise did not match the archive, and measuring first is what showed it.** The plan says
      "across central and state lists"; in the real data **0** groups repeat across two documents of the same
      source and exactly **1** spans a central and a state list. The real overlap is between the two **sources**:
      the portal is primary from 2019 (ADR 0004) and the PDFs run to Jun 2025, so **19 months carry rows from
      both**, and **1,154 of 1,186 repeated groups were a portal row paired with a PDF row** - about 14% of silver
      double-counted.
      **A finding = batch number + alert month + manufacturer + product + `is_spurious`**, every part required:
      - **The product had to be in the key.** One maker reuses batch `TST2301` across five different injections
        (Trenbolone Acetate, Trenbolone Enanthate, Nandrolone Blend, Boldenone, Stanozolol). Keyed on batch +
        month + maker alone, all ten rows collapse into one "duplicate" and five findings become one.
      - **Placeholder batch numbers are excluded** (42 rows): `"not applicable"` (22), `"not mentioned"` (7),
        `"nil"` (4), `"--"` (4), `"-"` (3), `"not given"`, `"na"`. Grouping on those merged unrelated medicines.
        5 of the 7 were already in `manufacturer_name.py`'s `PLACEHOLDER` set, so that set is **reused** rather
        than copied into a second list that could drift apart.
      - **Nothing merges on a missing key part.** Spark's `groupBy` treats NULL as a value, so keying on a
        nullable column quietly merges rows whose maker is merely *unknown* - which is how 10 spurious rows first
        appeared to duplicate NSQ findings, both having no canonical maker. A row missing any part gets its own id
        from `(source_key, page, row_index)`, **proven unique across all 8,322 rows** before relying on it.
      - **`is_spurious` is in the key** so a counterfeit report can never merge into a manufacturer's own record
        (CLAUDE.md Section 6). Since `manufacturer_canonical` is always NULL on a spurious row, the maker part
        falls back to `name_on_pack` - the right identity for matching two reports of the same counterfeit, and
        still attributed to nobody.
      **Harith's decisions:** the **portal row wins** (its dates parse better on exactly these pairs, 95% vs 90%,
      and its text is cleaner); **content columns fill gaps from the twin**, which is what keeps the 2 rows where
      only the PDF carries text - one a firm's reply reading *"The actual manufacturer (as per label claim) has
      informed that the impugned batch..."*, a real company stating a batch is not theirs; **provenance columns
      are never blended**, so one document's `page` can never sit beside another document's key; the redundant
      **bulk file is dropped**; and **exact matching only** - ~6 pairs whose product text differs
      (`"Fem creme Bleach"` vs `"Fem cream Bleach"`) stay as two rows, because a missed merge beats a wrong one
      and RapidFuzz would merge `Trenbolone Acetate` with `Trenbolone Enanthate`.
      **Verified on the real archive: silver 8,322 -> 7,128 rows**, and the arithmetic closes exactly: -16 bulk,
      -1,144 merged across 2+ documents (1,136 groups), -34 merged inside one document (31 groups). **1,136 rows
      name another document** in `also_reported_in` (exactly the cross-document group count; the 34 within-document
      merges leave it empty, because it records other *documents*, not other rows). Every merge was portal-won:
      `nsq`<->`state-nsq` 627, `nsq`<->`central-nsq` 508, `nsq`<->`combined` 1. **Null `alert_month`: 0. Bulk
      rows: 0. Re-running dedup on silver returns 7,128** - idempotent, which Phase 5's own acceptance test
      ("re-runs don't create duplicates") depends on.
      Tests: 22 unit. A mutation check of all 8 rules (product out of the key, placeholders allowed, the NULL
      guard removed, provenance blended, `is_spurious` out of the key, the PDF preferred, the bulk file kept, an
      unstable tie-break) made exactly the matching test(s) fail each time.
      ⚠️ **Counts change meaning from here on:** a batch flagged in both a state list and the portal is now one
      finding, not two. Earlier per-source row counts (Phase 2's included) are row counts, not finding counts.
- [x] 8. Great Expectations suite (2026-11-16). New `quality/` uv project (GE 1.25, pyarrow); `silver.py` reads
      silver, `suite.py` holds the 29 expectations. **Everything in the plan's list is covered** (required fields
      not null, valid dates, batch number format, category values in an allowed set, row counts in range), plus
      the spurious rule and a one-row-per-finding check.
      **Reads silver with pyarrow, not Spark** (approved stack: pandas/pyarrow). Silver is ~7,000 rows, so Spark
      would mean a JVM and ADR 0008's 686 MB SDK bundle to read what pandas handles in **a second** - the whole
      suite runs in ~2 s instead of ~10 min, which is what makes it usable as a gate. Silver is partitioned by
      `source_dataset`/`alert_month`, so those two columns live in directory names, not in the files;
      `partitioning="hive"` is what puts them back (a test proves it, since without it they are simply missing).
      **Thresholds are measured, not guessed, and where real data legitimately breaks a rule the exception is
      written down instead of the rule being dropped:**
      - `dates_valid` is False on **17 rows** - genuine CDSCO typos from step 3 - so the rule allows 99%; a test
        proves 1-in-100 passes while 50% fails, which is what catches a parser inverting dates wholesale.
      - **7 of 7,128 batch numbers contain no letter or digit** (2 blank, rest punctuation like `"--"`): allowed
        at 99.9%. And **no format regex beyond "has some text"**, because 22 real batch numbers carry mojibake
        (`"T?18909"`) and 62 contain a line break - a stricter rule would fail correct rows.
      **The vocabularies are restated in the suite, deliberately NOT imported from `drugwatch_spark`.** A check
      that imports the thing it checks only proves the code agrees with itself; stating them independently means
      that if someone edits the category list in the pipeline, the suite fails and a person decides which side is
      right. That is the point of a gate.
      **Verified: 29/29 expectations pass on the real 7,128-row silver** (`exit 0`; the report still prints
      "batch_no 7 bad" and "dates_valid 17 bad", so the tolerated exceptions stay visible rather than hidden).
      Exits 1 on failure, for Phase 5's Airflow to act on.
      Tests: 36 unit + 1 integration against real RustFS. **Every test breaks one rule and asserts the suite
      catches it** - a gate that only ever goes green is indistinguishable from no gate. That includes the
      ethics checks: a spurious row attributed to a manufacturer, a cleaned name left on one, and a
      `name_on_pack` on an ordinary row all fail the suite.
      Found by writing a test: `RUSTFS_ENDPOINT` without a scheme (`"localhost:9000"`) split into scheme
      `"localhost:9000"` and an empty host, so the client just failed to connect with nothing explaining why -
      now rejected loudly by `endpoint_parts()`. CI: `quality` added to the `python` job matrix.
- [x] 9. **Pandas vs PySpark benchmark** (2026-11-18). `pandas_pipeline.py` (the same job in pandas),
      `compare_engines.py` (proves both agree), `benchmark.py` (times and measures them). Written up in
      `docs/benchmarks.md`.
      **"The same job" is proven, not asserted.** The pandas version **imports the same logic** - the pure Python
      functions the Spark job wraps in UDFs (`split_combined_cell`, `strengths_in`, `split_brand_generic`,
      `clean_manufacturer_name`, `cluster_variants`), the same regex constants (`dosage_form.PATTERNS`,
      `failure_category.CATEGORIES`) and the same `SILVER_COLUMNS`. Only what Spark expressed as `Column`
      operations was written twice. **`compare_engines` then checks the real outputs: 7,128 rows x 32 columns
      agree exactly.**
      **Measured fairly:** each engine in its own subprocess (Spark's work is in a JVM the Python process cannot
      see); peak memory sampled across the whole process tree every 100 ms (`getrusage` misses a running JVM);
      two times reported - the pipeline itself and the total including JVM start-up and jar resolution, because a
      monthly Airflow task pays start-up every run; both write silver to a local temp dir, which forces each
      engine to materialise every row while keeping object-store writes out of the comparison.
      **Result on the full archive (median of 3, Apple M2, 8 GB):**
      | Engine | Pipeline | Total | Peak memory |
      |---|---|---|---|
      | **pandas** | **6.1 s** | **6.5 s** | **181 MB** |
      | PySpark | 111.4 s | 124.1 s | 2,723 MB |
      **~19x faster, ~15x less memory at this size.** Spark's figure is a range, not a point: 56-132 s across
      two sessions for identical work, while pandas stayed within 0.7 s of its median - its own variance exceeds
      pandas' entire runtime.
      **The honest caveat is in the doc:** this pipeline is UDF-heavy, so Spark serialises every row out to a
      Python worker and back; a Spark-native rewrite in pure SQL expressions would close much of the gap. It is a
      fair measurement of *this* pipeline, not a general claim about the engines. Also recorded: why the project
      still uses PySpark (the architecture and the learning goal), and that pandas would comfortably serve this
      project's data for millions of rows yet.
      **The benchmark improved the code it measured:** the first pandas dedup used
      `transform(col.ffill().bfill())`; `GroupBy.first()` - which *is* "first non-null per column", the same thing
      Spark's `first(ignorenulls=True)` does - **halved the runtime (12.3 s -> 6.1 s) and cut peak memory 2.3x**,
      output still identical. It also removed a pandas deprecation (object-dtype downcasting).
      Found and handled: **Java's `yy` means 2000-2099, Python's `%y` means 1969-2068**, so `"Apr-95"` is 2095 to
      Spark (dropped by the 1990-2049 rule) and 1995 to pandas (kept) - the same input giving different output.
      `_java_two_digit_year()` applies Java's rule; a test pins it.
      Tests: 19 new (249 in `spark/` total), including **5 fixtures run through both engines and compared cell by
      cell** (ordinary rows, a portal combined cell, a spurious report, one maker spelled two ways, and awkward
      values like `29.09.2021`, `T?18909` and `"Not Applicable"`).
      Also noted in the doc: `build_silver.main()` takes ~10 min against the ~2 min measured here for the same
      work, because every `count()` in its report re-runs the whole UDF chain.

**Done when:** silver data passes all GE checks, manufacturer duplicates are resolved, and the Pandas vs PySpark
benchmark is recorded.

**Done-when check (2026-11-18): all 3 met — Phase 3 is COMPLETE.**
- ✅ **Silver passes all GE checks** — 29/29 expectations on the final 7,126-row table, exit 0 (step 8).
- ✅ **Manufacturer duplicates resolved** — the automatic 98+ clustering plus **Harith's reviewed decisions on
  all 260 borderline pairs** (195 merges, 65 kept apart): **3,302 cleaned names → 2,609 canonical makers.**
- ✅ **Benchmark recorded** — `docs/benchmarks.md` §1 (pandas 6.1 s / 181 MB vs PySpark 111.4 s / 2,723 MB on
  identical output).

**Final silver: 7,126 rows, 32 columns**, written to `s3a://silver/nsq/` partitioned by source and alert month.
The review also removed **2 real double-counted findings**: CDSCO listed batch `DL5201` and batch `25CT0314`
twice each in one document under two spellings of the maker (`Digital Vision ... 20 176` vs `... 176`;
`Consern Pharna Ltd.` vs `Consern Pharma Limited`), same product and same failure reason both times. Merging the
maker spellings is what revealed them as one finding each.
Both engines re-checked after the merges: **identical, 7,126 rows x 32 columns agree exactly.**

⏳ **Carried into Phase 4, not blocking:** whether `is_spurious` needs a **row-level** signal rather than CDSCO's
document-level category (78 rows sit in "combined NSQ/spurious" documents; today's data is attributed correctly,
a future combined document with a spurious section would not be).

---

## Phase 4 — Warehouse (gold)

Approved 2026-11-18. Plan: `DRUGWATCH_PHASES.md` §9 Phase 4. Goal: analytics-ready data in Postgres. Steps 1-2 done; step 3 in progress (piece 1 of 3).

- [x] **Step 1 — Load silver into the Postgres `staging` schema** (2026-11-18)
      `warehouse/` is a new uv project (ADR 0011): **pyarrow + psycopg 3**, not Spark JDBC. The reason is
      Phase 3's own benchmark — Spark costs ~2 min and ~2.7 GB for exactly this table, against **1.2 s** for
      this loader. psycopg is barely an addition: `dbt-postgres` ships a Postgres driver anyway.
    - `schema.py` — the 32 silver columns written out in full, with their Postgres types. Silver's types are
      **kept**, not flattened to text: `date` stays `date`, `is_spurious` stays `boolean`, the three list
      columns (`strengths`, `failure_categories`, `also_reported_in`) stay `text[]`. No constraints and no
      primary key: those rules belong in dbt tests (step 4), where a failure is a named report on data you can
      query rather than a crash in the middle of a load. One extra column, `loaded_at timestamptz DEFAULT now()`,
      so dbt and Airflow can see how fresh gold is; `COPY` never sends it.
    - `load_silver.py` — reads silver through **`drugwatch_quality.silver.read_silver()`**, the same reader the
      Great Expectations gate uses, so in Phase 5's *validate → load* DAG "what passed" and "what landed" are
      provably the same rows. Loads with `COPY ... FROM STDIN` (Postgres' bulk path, one stream instead of one
      INSERT per row).
    - **Full refresh in one transaction:** `TRUNCATE` + `COPY` commit together. Re-running is idempotent
      (Phase 5 requires that), no reader ever sees an empty or half-loaded table, and any failure rolls back
      the TRUNCATE too — a failed load can never half-replace good data.
    - Three guards, each mutation-checked: an **empty silver is refused** before the TRUNCATE (it would wipe the
      table); a **column set that doesn't match** is refused (a Phase 3 schema change must stop the pipeline,
      not quietly load 31 of 32 columns); the **row count is verified inside the transaction** and a mismatch
      rolls back.
    - Value conversion, each case from real silver: numpy scalars/arrays → plain Python; NaN / NaT / pd.NA →
      NULL (checked *after* the list branch, or an empty `strengths` list would become NULL); `page` float64 →
      `integer` (it is only a float because 97% of rows are NULL).
      **Verified (2026-11-18):** `7126 rows, 32 columns` read, `loaded 7126 rows into staging.silver_nsq`
      in **1.2 s total**, re-run leaves 7,126.

      | source_dataset | rows | spurious | makers | months |
      |---|---:|---:|---:|---|
      | nsq | 6,917 | 0 | 2,568 | 2019-01 .. 2026-09 |
      | combined | 77 | 0 | 65 | 2018-05 .. 2018-08 |
      | spurious | 77 | 77 | 0 | 2024-04 .. 2026-09 |
      | state-nsq | 30 | 0 | 26 | 2024-05 .. 2025-06 |
      | central-nsq | 25 | 0 | 12 | 2017-07 .. 2025-06 |

      **24 tests pass** (22 unit + 2 against the real local Postgres, which is what proves the type adaptation:
      `text[]` comes back as a list, `date` as a date, NULL as None). Mutation-checked: dropping the list branch,
      the float→int conversion or the TRUNCATE each makes tests fail.
- [x] **Step 2 — dbt project, and its first staging model** (2026-11-18)
      `dbt/` is now a dbt project plus its own uv environment (dbt-core 1.12.7, dbt-postgres 1.11.0).
      `dbt build` succeeds: **1 model, 0 errors.**
    - **Schemas are named, not prefixed.** dbt's default would build a model configured `+schema: dbt_staging`
      into `gold_dbt_staging`; `macros/generate_schema_name.sql` overrides that to use the name verbatim. The
      layout is `staging` (the loader's landing table — dbt only *reads* it), `dbt_staging`, `dbt_intermediate`,
      `gold`. dbt never builds into the schema it reads from.
    - `models/staging/_silver__sources.yml` — declares `staging.silver_nsq` as a **source**, so the table name
      lives in one place and dbt can draw the lineage. Freshness is configured off `loaded_at`
      (warn at 45 days, error at 75: CDSCO publishes monthly), checked by `dbt source freshness` — **PASS**.
    - `models/staging/stg_nsq_sample.sql` — a **view** (materialising it would store a second, stale copy of
      silver). Thin on purpose: no joins, no filters, no business rules. It adds two things —
      `sample_id`, an md5 of the provenance triple `(source_key, page, row_index)`, which is unique across all
      7,126 rows (verified in SQL first) and stable across rebuilds; and `alert_month_start`, the alert month as
      a real date for time axes and the future `dim_date`. `alert_month` itself stays text: 'YYYY-MM' names an
      alert, not a day.
      Little is renamed, and nothing is renamed for the sake of it — Phase 3 already chose good names. Listing
      all 33 columns out is still the point: this file is the contract, so a new silver column cannot appear
      downstream by accident and a deleted one fails here rather than deeper in the graph.
      **Verified (2026-11-18):** `7126 rows, 7126 distinct sample_id, 0 null ids, 0 null alert_month_start`,
      alert months `2017-07` … `2026-09`.
    - **Telemetry off** (`send_anonymous_usage_stats: false`): dbt phones home by default, and a public-interest
      project should not send statistics its users were never asked about.
    - **Found while testing the password guard:** dbt-core runs `load_dotenv(find_dotenv(usecwd=True),
      override=False)` at start-up, so running dbt anywhere inside the repo silently loads the repo-root `.env`
      with no `--env-file`. Proved it by running dbt from outside the repo with `POSTGRES_PASSWORD` unset: the
      connection is then refused. Consequences recorded in `profiles.yml`: a shell variable wins over `.env`
      (`override=False`), and CI has no `.env` at all.
    - **CI gained a `dbt` job** that runs `dbt parse` — every model's SQL and every YAML file, no database
      needed (checked: `dbt parse` needs no credentials and opens no connection). `dbt build` needs Postgres and
      the loaded silver, so it stays a local and Phase 5 step.
    - **Noted for step 4's tests:** 2 pairs of rows share the Phase 3 finding key (batch + month + maker +
      product + spurious) — the same two Covishield batches reported in both a central PDF and the portal, with
      **no manufacturer printed**. Phase 3's dedup requires every key part to be present, so it correctly left
      them alone ("a missed merge is better than a wrong merge"). A uniqueness test in step 4 must therefore be
      on `sample_id`, not on the finding key.
- [ ] Step 3 — star schema (§8.1) and marts (§8.2) — split into 3 pieces, like Phase 3 step 5
    - [x] **Piece 1 — the star schema: 3 dimensions and the fact** (2026-11-18)
          `dbt build` → **5 models, 0 errors**: `dim_drug` 5,651 · `dim_manufacturer` 2,609 ·
          `dim_date` 7,305 · `fact_nsq_sample` 7,126 · `stg_nsq_sample` (view). Marts are tables
          (`+materialized: table`): gold is read by Superset, the API and the ML pipeline, which should
          read stored rows, not re-run the whole SQL chain per page load.
        - **`fact_nsq_sample`** — one row per finding, `sample_id` carried straight through from staging.
          Two CLAUDE.md §6 rules are enforced here, not left to whoever queries it: a **spurious report has
          no `manufacturer_id`** (the name on a counterfeit pack is the copied brand, kept apart in
          `name_on_pack`), and **provenance travels into gold** (source file, page, row index, SHA-256, URL),
          so every public view can link to the original CDSCO document. Joins to the dimensions are LEFT
          joins: 128 rows have no manufacturer printed (77 spurious + 51 CDSCO never named), and an inner
          join would silently under-report the archive.
        - **`dim_manufacturer`** — 2,609 companies, with `name_variants` (every cleaned spelling that
          resolved to it; 484 have more than one) and `latest_address`. Holds **no counts**: a dimension
          describes a thing, the marts count. Spurious rows are excluded, so a faked name can never enter
          the manufacturer list.
        - **`dim_drug`** — grain is the product name as printed, which was **measured, not assumed**:
          across all 7,126 rows no product name ever carries two different dosage forms, generic/brand names
          or strength lists (0 exceptions). Differently-printed names for the same medicine are **not**
          merged — that needs the same reviewed evidence Phase 3 used for manufacturers.
        - **`dim_date`** — a row per day, range **derived from the data** (whole years from the earliest to
          the latest date anywhere in the fact; expiry dates reach 2034), so it cannot go stale. `date_id`
          is YYYYMMDD as an integer, the classic star key.
        - **Verified (2026-11-18)** by query, before any dbt test exists: `7126 fact rows, 7126 distinct
          sample_id, 0 orphan drug_id, 0 orphan manufacturer_id, 0 orphan alert_date_id, 0 spurious rows
          attributed to a manufacturer, 0 rows missing source_url`. A real question answered through the
          star (top reported manufacturers, joined across all three dimensions) returns sensible rows —
          e.g. Martin & Brown Bio-Sciences, the 11-spelling cluster Phase 3 resolved.
        - **Three §8.1 columns are deliberately absent, not forgotten:**
          `state`/`city` on dim_manufacturer and `reported_state_id`/`lab_type` on the fact wait for piece 2
          (the address is still one unparsed string); **`drug_class` has no source at all** — nothing in the
          archive classifies a medicine, and inventing classes from name fragments would be a guess dressed
          as a fact. ⏳ **Decision needed from Harith before `mart_drug_class_failures` (§8.2) can be built.**
        - **One divergence from §8.1, already decided:** the fact keeps `failure_categories` (a list), not a
          single `failure_category`. The plan predates ADR 0009's finding that 22.6% of rows name more than
          one failed test.
    - [x] **Piece 2a — `dim_state` and the manufacturer's state, read out of the address** (2026-11-18)
          There is no state field in the archive: one address string per manufacturer, typed by whoever
          wrote the alert. So a **reviewed vocabulary seed** (`seeds/india_state_alias.csv`, 62 spellings
          of the 36 states and UTs: official names, real variants — Orissa, Tamilnadu, Gujrat, Uttaranchal —
          and abbreviations HP/U.P./HR/J&K) is matched against a normalised copy of the address.
          dbt **seeds** are CSV reference tables dbt loads into the warehouse: reviewable as a table,
          diffable in git, and a new spelling is a one-line change with no SQL to re-read.
        - **Three traps, each found by reading real addresses before writing the rule:**
          1. **There is a village called Kerala — in Gujarat** ("GIDC Kerala, Bavla, Dist. Ahmedabad,
             Gujarat"). 5 companies sit there. So a row matching two different states resolves to **null**,
             never to the first or the longest match.
          2. **Road names carry state names**: "14/4, Delhi-Mathura Road, Faridabad, Haryana" is in Haryana.
             Caught by the same two-match rule.
          3. **47 addresses contain a second company's address** after a marketer marker — often in another
             state. Everything from the marker on is cut before matching. The markers are counted as whole
             words, not imagined: `mrkt` 30, `marketed` 7, `mrk` 6, `mkt` 2, `markt` 1. **`market` is
             deliberately not a marker** though it occurs 4 times — it is part of real addresses
             ("Vasavi Pharma Market Complex"), and a prefix match would have truncated them.
             Widening the markers from 3 spellings to 5 resolved 3 conflicts, and correctly *lost* one
             match whose only state was the marketer's.
        - Matching normalises first — lower case, dots dropped (`H.P.` → `hp`, `(M.P)` → `mp`), other
          punctuation → space, `&` kept so `J&K` survives — and uses Postgres' `\m…\M` word boundaries,
          so `hp` cannot match inside `HPSIDC`. Aliases are stored already normalised, so there is no
          regex escaping to get wrong. Every answer keeps `state_match_evidence` (which alias produced it).
        - **Verified (2026-11-18), 2,609 companies:** `matched 1,730 (66.3%)`, `no_state_in_address 820
          (31.4%)`, `no_address 47 (1.8%)`, `conflicting_states 12 (0.5%)` — all 12 read and confirmed as
          genuine ambiguities (Kerala-in-Gujarat ×5, Delhi road names, a "Works at:" second factory).
          `0 orphan state_id`. Top states: **Himachal Pradesh 678, Uttarakhand 200, Gujarat 176, MP 81,
          Haryana 79** — which matches India's actual pharma geography (the Baddi–Solan belt), a sanity
          check the number would have failed if the matching were wrong.
        - **Restructured to avoid a circular dependency:** `int_manufacturer` (the aggregation) →
          `int_manufacturer_state` (reads the address) → `dim_manufacturer` (joins them). Intermediate
          models are views: build steps, not something anyone queries.
        - `dim_state` is built **from the seed, not from observed values**, so a state with no findings
          still has a row and a map shows "0 reports" instead of a gap.
        - ⏳ **Open, measured: 820 companies still have no state.** 653 of them (79.7%) print a PIN code,
          so a PIN-prefix → state mapping is the largest available gain — but 2-digit prefixes are
          ambiguous for every state that was split (UP/Uttarakhand, AP/Telangana, Bihar/Jharkhand,
          MP/Chhattisgarh, Maharashtra/Goa, TN/Puducherry), so it needs a careful reference table and
          Harith's OK. Others print only a city ("Jejuri, MIDC, Pune"), or an abbreviation the vocabulary
          rejects on purpose: **`Raj.` cannot be added safely** — one real Haryana address reads
          "Sector 38, HSIIDC, Raj, Sonipat", where `Raj` is part of a name, and normalisation drops the dot
          that would have told them apart.
    - [x] **Piece 2a-ii — the rest of the states, from a PIN-prefix map learned from the data** (2026-11-19)
          **Coverage: 1,730 → 2,006 of 2,609 companies (66.3% → 76.9%).** `dbt build`: 11 models, 0 errors.
        - **The reference table nobody had.** The obvious way to turn a PIN into a state is a lookup table
          of India's postal prefixes. We do not have one, and writing it out from memory would be inventing
          reference data for a public dataset — wrong entries would be invisible and permanent. India's
          2-digit prefixes are also genuinely ambiguous for every state that was ever split
          (UP/Uttarakhand, AP/Telangana, Bihar/Jharkhand, MP/Chhattisgarh, Maharashtra/Goa, TN/Puducherry),
          and `24` — the single biggest bucket, 112 companies — is exactly one of them.
        - **So the map is learned from the data we already trust.** 1,421 companies both name their state
          *and* print a PIN. Grouped by the first 3 digits that is evidence: `int_pin_prefix_state` keeps a
          prefix only where every known company agrees (13 of 151 prefixes dropped — exactly the split
          states) **and** at least 3 companies agree (`pin_prefix_min_observations`, a dbt var).
          **59 prefixes accepted**, resolving **280** more companies.
        - **Validated by holdout, and the first attempt at validating it was wrong.** Checking the map
          against the rows it was learned from gave "0 disagreements" — tautological, since unanimity was
          computed over those very rows. The real test learns from one arbitrary half (split on the md5 id)
          and predicts the other, where the state is known independently: **99.78% agreement at threshold 3
          (460 of 461), 99.59% at 2** — so 3 was chosen. Kept as `analyses/pin_prefix_holdout.sql` so the
          claim can be re-run, not just asserted. The one error is prefix `244` (Moradabad UP vs Kashipur
          Uttarakhand), which is the shape of the residual risk: always between two neighbours.
        - **Reading the holdout's disagreements found two real bugs**, neither of which the earlier
          checks had shown:
          1. **Plot numbers masquerading as PINs.** Reading the PIN off the punctuation-flattened string
             turned "Khasra No. 140-141" into 140141 and "393/394, Melli Jorethang Road" into 393394. The
             PIN is now read from the **original** text with only whitespace allowed inside it ("247 667"
             is a PIN, "140-141" is not) — the first now yields nothing and the second correctly finds the
             real PIN later in the address (737121, Sikkim).
          2. **A state name that is only a road name.** "P.O. Delhi Road, Fazilpur, Sonepat-131001" and
             "194, Mile Stone, Ambala-Delhi Highway" are both in Haryana. 10 addresses do this, so a match
             followed by road/highway/bypass/marg/NH is discarded. The two-match rule had not caught them
             because the real state was never spelled out — only the PIN gave it away.
        - Restructured again so the two signals cannot drift: `int_manufacturer_address` prepares the
          address once (normalise, cut at the marketer, extract the PIN) and both the name matcher and the
          PIN map read it. The PIN map learns **only** from name-derived answers, never from its own
          output.
        - **Verified (2026-11-19):** `address_names_the_state 1,726 (66.2%)`, `learned_pin_prefix 280
          (10.7%)`, `unresolved 603 (23.1%)`, `conflicting_states 10` (down from 12 — the road guard fixed
          two), `0 orphan state_id`. Top states **Himachal 717, Uttarakhand 263, Gujarat 199, MP 112,
          Haryana 98, Maharashtra 76** — Uttarakhand gained 62 from PINs and Maharashtra 33, which is the
          UP/Uttarakhand and Goa/Maharashtra ambiguity being resolved by evidence rather than by assumption.
    - [x] **Piece 2b — `lab_type` and the reporting lab's state, from `reported_by`** (2026-11-19)
          `dbt build`: **14 models, 0 errors.** `lab_type` on 6,702 of 7,126 rows (94.0%);
          the reporting lab's state on 6,935 (97.3%); `0 orphan reported_state_id`.
        - **Why `lab_type` matters more than it looks.** CDSCO's own laboratories (CDL, CDTL, RDTL) test
          samples drawn nationwide; a state laboratory tests samples drawn in its own state. So the two are
          not comparable, and the proof is in the data: **498 findings tested in West Bengal were made in
          Himachal Pradesh**, 339 tested in Chandigarh were made in HP, 287 tested in Assam likewise.
          Central labs cover 11 lab-states but 26 manufacturing states. Anyone grouping findings by the
          reporting state and calling it "unsafe medicine by state" would put West Bengal on top purely
          because CDL Kolkata does the testing. The fact therefore carries **two different state fields**:
          `reported_state_id` (the lab) and `dim_manufacturer.state_name` (the maker), with that warning in
          both models' comments.
        - **Two reviewed seeds, both auditable as tables:**
          `lab_type_marker` (29 rows) maps each abbreviation to Central or State *with its expansion*, so a
          reader who does not know what RDTL stands for can still check the table. Central wins over State
          where both match, because the central phrases are more specific ("Central Drugs Testing
          Laboratory" contains "drugs testing laboratory") — though **0 rows actually matched both**, so the
          rule is a guard, not something in use.
          `lab_city_state` (33 rows) maps each laboratory city to its state.
        - **The city seed is checked against the archive, not trusted.** Some reporter strings name both the
          city and the state ("DTL, Bengaluru, Karnataka", "LUCKNOW, Uttar Pradesh"), which makes the seed
          testable: **15 of its 33 cities are confirmed that way, with 0 disagreements** (bengaluru, bellary,
          lucknow, kathua, srinagar, baddi, kolkata, sambhajinagar, thiruvananthapuram, ernakulam, pune,
          thrissur, bhopal, bhubaneswar, guwahati). The rest are cities the archive never spells a state out
          for (Mumbai, Chennai, Jaipur, Hyderabad, Indore…), and the CSV's `verified_against_data` column
          says which is which. Kept as `analyses/lab_city_crosscheck.sql`; step 4 makes it a dbt test.
        - **Every marker and city came from reading the unresolved tail**, then re-measuring: `FDTL`,
          `SDFTL`, `BDCL`, `FDA`, `govt analyst`, `food & drugs laboratory` (the ampersand form my first
          marker missed) and a bare `Lab`; cities Thrissur, Ernakulam/EKM, TVPM, Konni, Indore, Bhopal,
          Patna, Baddi, Kathua, Jodhpur, Sambhajinagar, US Nagar. That took `lab_type` from 91.4% → 94.0%
          and the lab's state from 93.3% → 97.3%.
        - **Left unresolved on purpose:** `MDTL Kathua` (6 rows) — I could not establish whether a Mini Drug
          Testing Laboratory is state-run without guessing, so it stays null. "Govt. Analyst, Haryana,
          Chandigarh" names two states, so the unanimity rule leaves it null — correct, since the Haryana
          analyst sits in Chandigarh. "Karnataka", "Puducherry" and "Not applicable" name no laboratory, so
          they have no type. 100 rows have no reporter at all.
    - [x] Piece 2 complete — `dim_state`, the manufacturer's state, `lab_type`, the lab's state
    - [x] **Piece 3 — four analytical marts of §8.2** (2026-11-19)
          `dbt build`: **19 models, 0 errors.** `mart_manufacturer_trend` 85,924 ·
          `mart_repeat_reported_manufacturers` 500 · `mart_state_summary` 36 · `mart_ml_features` 85,924.
        - **`int_manufacturer_month`** — one shared dense manufacturer × month grid (the only intermediate
          model materialised as a table, since two marts read it). Dense matters: rolling and trailing
          windows are only correct over an unbroken series, and if the quiet months are simply missing then
          "reports in the last 6 months" silently becomes "reports in the last 6 months that had reports",
          which is never zero. The grid runs to the **archive's** last month, not each company's, because a
          company going quiet is a real signal.
        - **Windows are RANGE windows over dates, not ROWS windows over rows.** CDSCO published in **101 of
          the 111 calendar months** the archive spans, so "the previous 5 rows" is not "the previous 5
          months". Measured: a ROWS window differs on **209 of 85,924 rows (0.2%)**, over-counting by up to
          3 — small today, concentrated in the sparse early years, and free to do correctly.
        - **`mart_repeat_offenders` renamed to `mart_repeat_reported_manufacturers`.** CLAUDE.md §6 forbids
          calling a manufacturer fraudulent, and "offender" is a verdict; the table holds a count of alert
          months. It counts **alert months, not reports** — ten findings in one alert is one inspection
          sweep, one finding in each of ten months is a pattern that persisted — and ranks with
          **DENSE_RANK**, so tied companies share a rank (rank 4 is genuinely shared) and no public list
          implies an order the data cannot support. Top: Jackson Laboratories 49 alert months / 90 reports,
          Unicure India 46 / 95, Nestor Pharmaceuticals 30 / 40.
        - **`mart_state_summary` keeps the two state meanings in separate columns** (`reports_made_here`
          vs `reports_tested_here`, plus `state_lab_reports_tested_here` as the honest subset), with
          dim_state as the spine so all 36 states and UTs have a row and a map shows 0, not a gap.
        - **`mart_ml_features`** — plan §12's table: 85,924 rows, features only from months ≤ `as_of_month`,
          label from the 6 months after. Distinct counts (drugs, reporting states) are computed by joining
          the findings back over the window, because summing per-month distinct counts would double-count a
          drug reported in two months. Category shares are shares of **mentions**, not reports (ADR 0009),
          and `central_lab_share_12m` is **null, not 0**, when there was nothing to divide.
        - **Verified by independent recomputation of all 85,924 rows** (not a sample, and not reusing the
          model's own windows): `0 wrong reports_6m`, `0 wrong reports_12m`, `0 wrong labels`,
          `0 leaked labels`. Cutoffs run 2017-09 … 2026-09; the last trainable one is **2026-03**, exactly
          6 months before the archive ends. Label balance: **71,354 complete rows, 14.2% positive** — worth
          knowing now, because that imbalance is why Phase 7 reports PR-AUC and precision@K, not accuracy.
        - **Two §12 features cannot exist, and that is deliberate:** "any spurious-drug association" (a
          spurious pack names the copied brand, so those findings carry no manufacturer_id at all) and
          "share of reports by drug class" (⏳ no classification source — still open).
        - **Two §8.2 marts not built:** `mart_drug_class_failures` (blocked on the `drug_class` decision)
          and `mart_price_gap` (needs NPPA/Jan Aushadhi price data; Phase 1 found no bulk source for
          branded prices — a Phase 6 problem, not a Phase 4 one).
- [x] **Step 4 — dbt tests** (2026-11-19)
      `dbt build`: **57 nodes, 0 errors — 3 seeds, 16 models, 38 data tests.**
    - **31 generic tests** in the model YAML: `unique` + `not_null` on all five surrogate keys
      (sample_id, drug_id, manufacturer_id, state_id, date_id); `relationships` on all four foreign keys
      (fact → dim_drug, dim_manufacturer, dim_date, dim_state); `accepted_values` on `lab_type`,
      `reported_state_source`, `name_match_status`, `state_name_source` and `state_type`; `not_null` on
      `source_url`, `is_spurious`, `batch_no` and the alert month.
      Written in dbt 1.12's current form (test parameters under `arguments:`), so the build raises
      **0 deprecation warnings**.
    - **7 custom (singular) tests** — a singular test is a query selecting the rows that must not exist:
      - `assert_expiry_after_mfg` — the plan's own example, written as a **consistency** check rather than
        a flat rule: the archive really does contain impossible dates (17 CDSCO typos), and Phase 3's
        `dates_valid` flag is how they are marked. What must never happen is a typo passing itself off as
        valid.
      - `assert_no_spurious_attributed_to_manufacturer` — the CLAUDE.md §6 invariant. It holds by
        construction in three separate places; this is what notices if any one of them changes.
      - `assert_failure_categories_in_vocabulary` — ADR 0009's 15 values, **restated not imported** (a test
        that reads its expectations from the code under test cannot fail), unnesting the array because
        `accepted_values` compares a column to a list, not a list to a list.
      - `assert_fact_covers_every_staging_row` — a full outer join, not two counts: equal counts can hide
        an equal number of additions and losses.
      - `assert_mart_grains_are_unique` — all four marts' grains in one test. Break a grain and nothing
        errors; the numbers simply double.
      - `assert_ml_features_have_no_label_leakage` — step 3's manual check, promoted. Recomputes
        `reports_6m`, `reports_12m` and the label by date-range joins with no window functions at all, and
        fails on any disagreement.
      - `assert_lab_city_seed_agrees_with_the_archive` — the cross-check promoted from an analysis.
    - **Mutation-checked: every test proven able to fail**, not just to pass.

      | Mutation | Caught by | Rows |
      |---|---|---:|
      | fact attributes a spurious pack to the copied company | `assert_no_spurious_attributed_to_manufacturer` + `relationships` on manufacturer_id | 17 + 7 |
      | label window includes the cutoff month (leakage) | `assert_ml_features_have_no_label_leakage` | 3,110 |
      | fact quietly drops the 77 spurious findings | `assert_fact_covers_every_staging_row` | 77 |
      | dim_state stops collapsing its aliases | `unique_dim_state_state_id` | 17 |
      | every feature row duplicated | `assert_mart_grains_are_unique` | 85,924 |
      | a join key forgotten in mart_ml_features | **Postgres itself** rejected the SQL — honest to note that this one is caught by the database, not by a test | — |
    - **CI still runs only `dbt parse`.** The tests need Postgres *and* the loaded silver table, neither of
      which exists on a CI runner, so `dbt build` stays a local and Phase 5 (Airflow) step. That is the
      gap worth being honest about: these tests gate the pipeline, not the pull request.
- [x] **Step 5 — dbt docs for lineage** (2026-11-19)
      `dbt docs generate` builds the catalog from the warehouse plus every description written along the
      way. **19 of 19 models and seeds carry a description**; 67 of the 214 columns Postgres actually holds
      are described (31%) — the undescribed ones are passthrough columns whose meaning Phase 3 already
      fixed, and padding them would bury the 67 that say something.
    - Added `_intermediate__models.yml`, which is what took documentation coverage to 19/19: the six
      intermediate models had no descriptions, and they are exactly the ones a reader needs explained (the
      learned PIN map, the dense month grid, why the address is prepared once).
      It also added 6 more tests — `unique`/`not_null` on `int_manufacturer`, `int_pin_prefix_state` and
      `int_reporting_lab` — so **`dbt build` is now 63 nodes: 3 seeds, 16 models, 44 tests, 0 errors.**
    - **The lineage is derived, not drawn.** dbt works it out from the `ref()` and `source()` calls, so it
      cannot disagree with the code. Walked it back from the deepest mart to prove it:
      `mart_ml_features → fact_nsq_sample → int_reporting_lab → stg_nsq_sample → source silver_nsq`,
      with the three seeds hanging off `int_reporting_lab` and `int_manufacturer_month` joining from the
      side. Models per schema: `dbt_staging` 1, `dbt_intermediate` 6, `gold` 9.
    - `dbt docs serve --port 8081` browses it locally. Publishing it is a Phase 11/12 question (it exposes
      column names and row counts, nothing from the data itself), not a Phase 4 one.

**Done when:** `dbt build` succeeds with all tests passing.

**Done-when check (2026-11-19): met — Phase 4 is COMPLETE (closed by Harith, 2026-11-19).**
- ✅ **`dbt build` succeeds with every test passing** — `PASS=63 WARN=0 ERROR=0 SKIP=0`: 3 seeds,
  16 models, 44 data tests. Each test class is mutation-checked (step 4), so "passing" means the tests
  can fail, not just that they did not.
- ✅ **Deliverables** — dbt project (`dbt/`), star schema (`fact_nsq_sample` + 4 dimensions), marts
  (4 of §8.2's 6 — the section calls its list "examples"), dbt docs.
- ⏸ **Deferred, with reasons recorded:** `mart_drug_class_failures` (no classification source exists;
  needs Harith's decision) and `mart_price_gap` (no bulk branded-price source — Phase 1 §4.6, revisit in
  Phase 6).

**Gold layer as built:** `staging.silver_nsq` (7,126 rows loaded by `warehouse/`) → `dbt_staging` →
`dbt_intermediate` → **`gold`**: `fact_nsq_sample` 7,126 · `dim_drug` 5,651 · `dim_manufacturer` 2,609 ·
`dim_state` 36 · `dim_date` 7,305 · `mart_manufacturer_trend` 85,924 ·
`mart_repeat_reported_manufacturers` 500 · `mart_state_summary` 36 · `mart_ml_features` 85,924.

⏳ **Still open and carried forward:** `drug_class` (blocks one mart and one §12 feature); the row-level
`is_spurious` question from Phase 3; and `city` on dim_manufacturer (no closed vocabulary to match against).

**Done when:** `dbt build` succeeds with all tests passing.

---

## Phase 5 — Automation

Approved 2026-11-19. Plan: `DRUGWATCH_PHASES.md` §9 Phase 5. Goal: the pipeline runs itself every month.

- [x] **Step 0 — Airflow itself** (2026-11-19) — not one of the plan's five steps, but nothing else can start
      without it. **Airflow 3.4.0 on Python 3.13.5**, running on the host as a new `orchestration/` uv
      project, with its metadata in a new `airflow` database inside the existing Postgres (**ADR 0012**).
    - **Why on the host and not in Docker — decided by arithmetic, not taste.** Docker's VM allowance here
      is 5 GB; the four compose services use 245 MB; one Spark cleaning run peaks at **2.7 GB**
      (`docs/benchmarks.md`); Airflow 3's four components are ~1.5 GB. Airflow *and* Spark inside the same
      VM is ~4.5 GB of 5 — it fits on paper, and in Phase 3 it already failed in practice when another
      project's container held 3.4 GB and the Docker VM died mid-run. On the host, Spark keeps the whole
      machine, no JDK or 686 MB jar goes into an image, and no ~2.5 GB image is built over a slow link.
      The cost is honest and recorded: this is a deviation from "everything in compose", and Phase 12 has
      to decide how it deploys.
    - **A DAG task is a documented command.** `tasks.uv_task()` builds a `BashOperator` running
      `uv run --env-file ../.env python -m <module>` in one of the repo's project folders — exactly what
      `CLAUDE.md` §10 says — so any failing task can be reproduced by hand by copying it out of the log,
      and **secrets never reach Airflow**: the task reads `.env` itself. Retry policy is decided once in
      the factory (3 retries, exponential backoff from 2 min, capped at 15, 1-hour execution timeout);
      `dbt_task()` deliberately retries only once, because a failing dbt *test* is a data problem and
      retrying it just repeats the failure.
    - **Config is assembled in code, not written to a file.** `config.airflow_env()` builds every
      `AIRFLOW__*` variable from the same `.env` the rest of the repo uses, so the database password is
      never written into `airflow.cfg`. `cli.py` applies them with `setdefault`, so a variable already
      exported in the shell still wins. Example DAGs off, new DAGs paused at creation, LocalExecutor,
      API bound to 127.0.0.1:8082.
    - **First DAG: `raw_inventory`** — one task, verifying every file in `raw/` against the SHA-256
      recorded at download. Chosen because it is the smallest *real* task: `raw/` is the source of truth
      and is never modified (CLAUDE.md §5), so a silent change there would poison every future
      reprocessing run, and `drugwatch_ingestion.inventory` already exits non-zero on any problem — which
      is exactly what a task needs.
    - **Verified by running it, not by starting it** (2026-11-19):
      `db migrate` → `Database migration done!`; `dags reserialize` → `Creating ORM DAG for raw_inventory`;
      **`dags test raw_inventory` → `total 322 files 153.5 MB (checked: names, sidecars and SHA-256 of
      every file)`, `new_state=success`, DagRun `state=success` in 11.1 s.**
      `standalone` → UI on :8082 answers **HTTP 200** and `/api/v2/monitor/health` reports metadatabase,
      scheduler and triggerer all `healthy`. Processes stopped afterwards.
    - **5 DAG-integrity tests** (`tests/test_dags.py`): every DAG file imports, at least one DAG exists,
      no cycles, every DAG has a description *and* `doc_md`, and every task has retries. They need no
      database (SQLite in a temp dir), so unlike `dbt build` and the pipeline itself **they run in CI** —
      `orchestration` is now in the lint matrix.
    - **Two Airflow 3.4 specifics found by running it:** `dags list` reads the database, not the folder,
      so a new DAG needs `dags reserialize` (or a running dag-processor) before it appears; and
      `DagBag(...)` no longer takes `include_examples` — example loading is a config setting now.
    - **Known harmless noise:** `dags test` prints a `sqlalchemy.exc.MissingGreenlet` traceback while
      closing an async connection at teardown. The run still reports success. Checked both drivers —
      psycopg2 (Airflow's documented one, kept) and psycopg3 — and it appears with either, so it is an
      Airflow 3.4 teardown quirk, not a configuration mistake. Worth knowing before it eats an hour.
- [x] **Step 1 — the monthly pipeline DAG** (2026-11-19)
      `monthly_pipeline`: 10 tasks, CDSCO to gold. **Run end to end twice, both times 10/10 tasks
      successful**, the whole project in **4 minutes 0 seconds**.
    - **Shape of the run:** the three downloads in parallel → `verify_raw_archive` → the two bronze
      extractions in parallel → `build_silver` → `validate_silver` → `load_silver_to_postgres` →
      `dbt_build`. Validation sits **before** the load on purpose: bad data must never reach the
      warehouse the website reads.
    - **Two facts checked in the code before any wiring**, because getting either wrong would corrupt the
      archive on a schedule:
      1. `build_silver` writes `mode("overwrite")` — silver is replaced wholesale, never appended to.
         A DAG on top of an appending step would double the warehouse every month.
      2. The portal downloader **skips a stored month without even making a request** unless
         `--refresh`, and its own comment says why that matters: *state labs report late*, so a month's
         JSON keeps changing after the month ends. So the DAG asks for the interval's month **and the one
         before**, with `--refresh`. Unchanged bytes are never re-stored, so asking twice is free.
    - **Schedule `0 3 10 * *`** — the 10th at 03:00, not the 1st. CDSCO publishes a month's alerts
      *during* the following month, so a run on the 1st would mostly ask for a month nobody has published.
      Verified with `tasks render`: the command comes out as
      `--tab nsq --refresh --month 2026-11 --month 2026-10`.
    - `max_active_runs=1`: every task writes shared state, and two runs would mean two Spark jobs
      overwriting the same silver prefix. `catchup=False`: historical reprocessing is step 2's DAG.
    - **Per-task timings** (from the DAG run's own start/end markers):
      downloads 6.2 / 7.7 / 3.0 s · `verify_raw_archive` 5.9 s · bronze 33.8 s (PDF) + 3.4 s (portal) ·
      **`build_silver` 152.9 s** · `validate_silver` 5.5 s · `load_silver_to_postgres` 2.4 s ·
      `dbt_build` 19.4 s. **Total 240.3 s.**
    - **Idempotency demonstrated, not asserted** (the phase's done-when). Run 1 stored 4 new raw objects —
      `nsq`/`spurious` for 2026-10 and 2026-11, each `stored, 0 rows`, because CDSCO has not published
      those months yet; storing the empty snapshot records *"we asked and there was nothing"* instead of
      leaving a silent gap. **Run 2 reported all four as `unchanged`**, and every downstream figure was
      identical:

      | | Run 1 | Run 2 |
      |---|---|---|
      | raw/ | 326 files, 153.5 MB | 326 files, 153.5 MB |
      | silver | 7,126 rows (77 spurious) | 7,126 rows (77 spurious) |
      | Great Expectations | PASSED | PASSED |
      | loaded into Postgres | 7,126 | 7,126 |
      | `dbt build` | PASS=63 ERROR=0 | PASS=63 ERROR=0 |

      And in Postgres afterwards: `staging 7,126 / fact 7,126 / distinct sample_id 7,126 / makers 2,609 /
      feature rows 85,924` — no duplicates anywhere.
    - **A stale figure this run corrected:** `docs/benchmarks.md` said `build_silver.main()` takes ~10
      minutes. It took **152.9 s** here. The 10-minute note predates the `session.py` tuning (loopback
      RPC, `local[4]`, 2 GB driver) that took the Spark pipeline from 435.9 s to 53.2 s. The doc now
      carries the new measurement and says why the old one was wrong.
    - ⏳ **"Check for new alerts" is currently implicit**, and worth stating plainly: the hash check makes
      a no-change run harmless but not free — it still spends ~4 minutes rebuilding silver and gold from
      unchanged bronze. Short-circuiting on "nothing changed" needs the download outcomes as structured
      data, which is what step 5's run log will provide; doing it by parsing stdout would be fragile.
- [x] **Step 2 — the backfill DAG** (2026-11-19)
      `backfill_pipeline`: the same chain on months a person chooses. **Run end to end, 10/10 tasks
      successful**; a deliberately bad range fails the whole run in **11.8 s**.
    - **The shared chain is built once.** The monthly DAG's last seven tasks and the backfill's are the
      same, so `pipeline.processing_chain()` builds them and both DAGs call it; `monthly_pipeline.py` was
      refactored onto it. Copied, they would drift: a validation step added to one would silently not
      apply to the other, and the backfill would stop reproducing what the monthly run does. **No
      TaskGroup** — a group prefixes every task id (`process.build_silver`), which would orphan the run
      history the monthly DAG already has.
    - **Two parameters, and what they mean:** `refresh_downloads = false` (the default) reprocesses from
      `raw/` after a parser or cleaning fix, asking CDSCO for nothing already stored; `true` re-fetches the
      range to fill a gap or pick up a revision. Either way `raw/` is never modified (CLAUDE.md §5) — a
      refresh stores a *new* snapshot beside the old one when bytes differ, nothing when they don't.
      `start_month`/`end_month` are validated against the portal's 2019-01 start (ADR 0004), a backwards
      range, and a 120-month cap.
    - **There is no partial rebuild, deliberately.** `build_silver` reads all of bronze and overwrites
      silver, so two months and five years cost the same after the download step. Rebuilding one month in
      place would leave silver a mix of two code versions, and would compute manufacturer clustering over
      a *subset* — which produces different canonical names than the full archive does.
    - **The PDF downloader is absent from this DAG** on purpose: it fetches by document id, not by month,
      and a reprocess has no reason to re-list CDSCO's website (CLAUDE.md §7).
    - **Two bugs found by testing a deliberately bad range, neither visible from the tests:**
      1. **A permanent error was being retried.** The range `ValueError` is raised while a task's command
         is *rendered*, which Airflow treats like any task failure — so it retried with exponential
         backoff, taking **15 minutes** to report a typo that is wrong on the first millisecond. Fixed with
         a `check_month_range` gate that runs first with `retries=0`: the run now fails in **11.8 s**.
      2. **It then failed for the wrong reason.** `op_kwargs={"params": "{{ params }}"}` renders Jinja to a
         *string*, so the gate died on `TypeError: string indices must be integers` instead of printing the
         explanation it exists for. Tests green, task failing fast, message useless. Fixed by letting
         Airflow inject `params` by signature. **Only reading the actual message showed it.**
    - That second bug also improved the tests: the blanket rule "every task has retries" was wrong, and now
      says what was meant — **work tasks retry, validation gates must fail fast** — plus a new test that
      every work task has an `execution_timeout`. **24 tests pass**, and the month arithmetic's four guards
      are mutation-checked (year rollover Dec→Jan, backwards range, pre-2019, the 120-month cap).
    - **Verified by running it** (2025-01 … 2025-06, `refresh_downloads = false`): the gate printed
      `6 months: 2025-01 .. 2025-06` and `NOT asking CDSCO for anything already stored`, every month
      reported **`skipped`** (no request made), then silver `7126 rows (77 spurious)`, GE `PASSED`,
      `loaded 7126 rows`, `dbt build PASS=63 ERROR=0`.
    - **The backfill filled 5 real gaps while proving the point.** Its first attempt stored
      `cdsco-portal/spurious` for **2025-01 … 2025-05, each `stored, 0 rows`** — months never fetched
      before, where CDSCO published no spurious alerts (`raw/` 326 → 331 files). So `refresh off` means
      "don't re-ask for what's stored", not "don't ask for anything". The re-run then reported all six
      months `skipped`, and silver stayed at 7,126 because the new snapshots are empty.
    - ⚠️ **That first attempt also failed, environmentally, and it is worth keeping:** the Mac slept
      mid-run (`caffeinate -i` prevents idle sleep, not a lid close), the Docker VM's clock drifted, and
      RustFS's S3 API rejected the signed requests with `RequestTimeTooSkewed` (CLAUDE.md §10 documents
      this). **The retry policy worked and still was not enough**: both download tasks recovered
      (`up_for_retry` ×3 → `success`), while the two extraction tasks exhausted their retries, because 3
      attempts with backoff capped at 15 min covers ~7–15 minutes of transience, not a laptop asleep for
      two hours. That is the right behaviour — a DAG should not retry for hours — and it is the argument
      for step 4's failure email: recover from the brief failures, *tell someone* about the rest. It is
      also an argument for Phase 12 deploying to a VM that does not sleep. The VM clock resynced itself
      (drift measured at 0 s afterwards), so nothing in the code needed changing.
- [x] **Step 3 — retries with backoff; idempotent tasks** — satisfied by steps 0-2 rather than as separate
      work, and demonstrated rather than claimed: the retry policy lives in one factory (`tasks.py`:
      3 retries, exponential backoff from 2 min capped at 15, 1-hour timeout; validation gates 0 retries,
      dbt 1), idempotency was proven by running the monthly DAG twice with identical results and no
      duplicates (step 1), and the backoff was observed recovering real transient failures above.
- [x] **Step 4 — failure notifications by email** (2026-11-19)
      **Policy (Harith's decision): one email per task that fails after its retries are exhausted, and
      nothing else.** No mail for attempts the backoff recovers from, no success summaries.
    - **Why that policy, with evidence:** in step 2's failed backfill, both download tasks failed three
      times and recovered by themselves while the two extraction tasks ran out of retries. Under this
      policy that run sends **2 emails, not 12** — so every email means something a person must act on,
      which is the only way alerting survives contact with an inbox.
    - **How Airflow makes it exact, not approximate:** `on_failure_callback` fires when a task instance
      reaches `failed`; an attempt that will be retried reaches `up_for_retry` and fires nothing. So the
      policy is the framework's own semantics rather than logic we maintain.
    - `notifications.failure_message()` is a **pure function** returning (subject, html), so the content
      is unit-tested — the part that normally goes untested and then arrives at 3am missing the one fact
      someone needed. It carries the DAG, task, run id, attempts used, start time, the exception, a link
      to the log, **and the command to reproduce it by hand** (every task is a documented command,
      ADR 0012, which is what makes the email actionable). It also states why it was sent, so nobody
      wonders whether retries mail them.
    - **Credentials stay in one place.** `config.smtp_connection()` builds Airflow's `smtp_default`
      connection from the repo's own `SMTP_*` variables and exports it as `AIRFLOW_CONN_SMTP_DEFAULT`,
      so local dev (Mailpit) and production (Brevo) differ only by `.env`, and Spring Boot's watchlist
      emails will read the same variables (CLAUDE.md §8) — one set of credentials, not two that can
      disagree. Verified both shapes: Mailpit `localhost:1025 disable_tls=True`, Brevo-style
      `smtp-relay.brevo.com:587 disable_tls=False` (the inverse of `SMTP_STARTTLS`). New optional
      variable `ALERT_EMAIL_TO`, documented in `.env.example`.
    - Wired through `default_args` on all three DAGs rather than in the task factory, so a DAG cannot
      quietly be written without it.
    - **Verified both halves of the policy by running it** (2026-11-19):
      1. **Final failure sends one email.** A bad backfill range produced
         `[DrugWatch] backfill_pipeline.check_month_range failed after 1 tries` in Mailpit, whose body
         reads: `Attempts 1 of 1`, `Error the CDSCO portal starts at 2019-01 (ADR 0004); months before
         that exist only as PDFs... Got start_month=2018-01`, plus the log link.
      2. **A task that recovers sends nothing.** A throwaway probe DAG that fails once and then succeeds
         went `up_for_retry → success` with **0 emails sent** (Mailpit total unchanged at 1). The probe
         was deleted afterwards, including its metadata rows (`dags delete`, 4 records) so the UI shows
         no phantom DAG.
    - **7 new tests** (31 in `orchestration/` now), including that a context missing everything still
      produces a message: a callback that raises loses the alert entirely, so it must degrade rather
      than explode.
- [x] **Step 5 — the run log** (2026-11-19)
      Two tables in a new `ops` schema: `ops.pipeline_run` (one row per run) and `ops.pipeline_task`
      (one row per task). Written by a final `record_run_log` task plus a callback on every task.
    - **Every number comes from a structured source, never from scraped stdout** — the open question
      step 1 left. Parsing logs would have been the fragile answer: a reworded `print` would silently
      turn the run log into fiction. Instead: files from **RustFS itself** (through the downloaders'
      own `RawStore`), rows from **Postgres** (the warehouse's own answer, not a task's claim about
      it), dbt results from **`dbt/target/run_results.json`** (the artifact dbt writes for exactly
      this), and task states recorded by **each task as it finishes**.
    - **Tasks record themselves** rather than the summary querying Airflow's metadata database:
      Airflow 3 runs tasks in a subprocess that talks to the API server, so reaching into its
      database from inside a task is the kind of coupling that breaks on upgrade.
    - **dbt's artifact is checked for staleness.** dbt rewrites `run_results.json` on every
      invocation, so its `generated_at` is compared with this run's start; a file from an earlier run
      would otherwise be reported as this run's result — a lie that looks like data. Missing,
      unreadable and stale all store **nulls**, and `added_since()` returns null rather than 0 when
      either side is unknown, because "we do not know" and "nothing changed" are different answers.
    - **`trigger_rule="all_done"`** on the summary task, so a failed run is logged too: a run log that
      only records successes cannot answer "which checks failed", which is half of what the step asks.
      Both tables are keyed on (dag_id, run_id) and upserted, so re-running a run corrects its row
      instead of adding a second.
    - **Two bugs, both found by comparing output against a number already known — not by the tests:**
      1. **The raw-file count hid a third of the archive.** The first filter skipped `.json` keys,
         assuming sidecars were the only JSON — but **the portal's raw snapshots are JSON too**, so it
         reported 213 files where `inventory` says 331. Fixed by counting **sidecars**, which is
         strictly better: the sidecar is written second and is the store's own "this file is complete"
         marker, so a half-written file is not counted. Now reports 331, matching `inventory` exactly.
      2. **A perfect run was recorded as `failed`.** Airflow hands callbacks a `TaskInstanceState`
         *enum*; `str()` on it gives `TaskInstanceState.SUCCESS`, so the lookup for `'success'` matched
         nothing and all 10 tasks counted as failures. The tests passed plain strings and never saw a
         real enum. Fixed with `state_name()`, plus a regression test that imports the real enum. The
         one wrong row and its 10 task rows were deleted rather than left as a false record.
    - **Verified by running the pipeline** (2026-11-19): `status success · 10 tasks ok / 0 failed ·
      quality_check success · raw_files 331 · silver_rows 7,126 · gold_fact_rows 7,126 · dbt 63/63 ·
      189 s`, with all 11 task rows and their durations (`build_silver` 111 s, `extract_pdf_bronze`
      34 s, `dbt_build` 19 s).
    - **16 new tests** (46 in `orchestration/`), covering the delta rules (including that a *shrinking*
      count is reported as negative — silver really did shrink by 2 in Phase 3 when duplicate findings
      collapsed) and every way dbt's artifact can fail to be trustworthy.
    - ✅ **This also closes step 1's open question:** the download outcomes and row deltas now exist as
      structured data, so a future short-circuit ("nothing changed, skip the rebuild") has something
      reliable to read instead of stdout.

**Done when:** both DAGs run end-to-end with no manual steps and re-runs don't create duplicates.

**Done-when check (2026-11-19): met — Phase 5 is COMPLETE (closed by Harith, 2026-11-19).**
- ✅ **Both DAGs run end to end with no manual steps.** `monthly_pipeline` ran to completion four times
  (10/10 tasks, ~4 minutes each); `backfill_pipeline` ran to completion once with a chosen range
  (10/10 tasks), and fails a bad range in 11.8 s before touching CDSCO.
- ✅ **Re-runs don't create duplicates.** Proven at every layer, not argued: `raw/` 331 files both times
  (the downloads reporting `unchanged`/`skipped` rather than storing again), silver 7,126 rows, Postgres
  `staging 7,126 / fact 7,126 / distinct sample_id 7,126`, `dbt build PASS=63` — and the run log itself
  upserts, so the two runs are two rows, not four.
- ✅ **Deliverables** — two DAGs (`monthly_pipeline`, `backfill_pipeline`, plus `raw_inventory`),
  alerting (one email per final failure, verified in Mailpit; silence for recovered retries, verified
  with a probe), and the run log (`ops.pipeline_run`, `ops.pipeline_task`).
- **The delta rule, demonstrated:** the first recorded run shows blank deltas ("no previous run to
  compare with") and the second shows `0` ("nothing changed"). Different answers, deliberately.

**What one run does now:** download (portal NSQ + spurious for this month and last, with `--refresh`;
new alert PDFs) → verify every raw/ file against its SHA-256 → extract PDF and portal rows to bronze →
PySpark clean to silver → Great Expectations gate → load to Postgres → `dbt build` (16 models, 44 tests)
→ record the run. **~4 minutes, unattended, idempotent.**

⏳ **Open, carried forward:** a "nothing changed, skip the rebuild" short-circuit is now *possible*
(step 5 gives it structured data) but not built — a no-change run still spends ~4 minutes. And the
Phase 12 deployment must not inherit this machine's assumptions: ADR 0012 records that the DAGs run as
Harith's user with `~/.m2`, `~/.cache/uv` and a JDK already in place, and step 2 showed a sleeping laptop
is enough to exhaust a task's retries.

---

## Phase 6 — Analytics

Approved 2026-11-19. Plan: `DRUGWATCH_PHASES.md` §9 Phase 6. Goal: public, read-only dashboards.

**Four decisions taken at the start** (Harith, 2026-11-19 — "your recommendations"):
- **A. The price-gap dashboard moves out of Phase 6.** It needs branded-vs-generic prices, and there is
  **no price data anywhere downstream of `raw/`**: what exists is Jan Aushadhi's generic MRPs (14% priced
  at 0) and 169 NPPA PDFs of *ceiling* prices (legal maximums, not market prices). Branded MRPs sit behind
  Pharma Sahi Daam's request signing, which ADR 0003 rules out. Building it is a Phase 2–3-sized
  extraction + salt-matching job, not analytics. A fourth dashboard will be chosen from gold instead.
- **B. `drug_class`** gets a reviewed vocabulary for the top ~100 generic names, everything else
  `Unclassified` — the ADR 0009 shape. (Not yet built.)
- **C. Jupyter + matplotlib**, in a new `analytics/` project — **ADR 0013**.
- **D. No map of India.** State views are bar charts: India's boundary depiction is legally sensitive for
  an Indian public site, and Superset's bundled GeoJSON may predate the 2019 J&K/Ladakh split.

- [x] **Step 1 — the exploration notebook** (2026-11-19)
      `analytics/notebooks/01-explore-gold.ipynb`: 10 code cells over the gold layer, executed end to end.
      Findings written up as aggregates in **`docs/analytics-findings.md`**.
    - **Reads gold only, in a read-only transaction.** `drugwatch_analytics.gold.query()` sets psycopg's
      `read_only`, so the database refuses a write from a notebook cell — verified by a test that expects
      `ReadOnlySqlTransaction` when the notebook path tries `CREATE TABLE`. Exploration runs against a
      warehouse that took a Spark job to build; a stray `DELETE` at midnight should be impossible, not
      merely unlikely.
    - **Notebooks are committed with outputs cleared, and that is enforced.** A notebook's output *is*
      real CDSCO rows (ADR 0003). `repo-checks.sh` gained a check that fails on any tracked `.ipynb`
      carrying outputs, with the `nbconvert --clear-output` command in the message. Mutation-checked:
      passes clean, exits 1 on a notebook with outputs.
    - **Four findings that change what gets built** (full numbers in `docs/analytics-findings.md`):
      1. **The rising line is testing effort, not falling quality.** Findings and the number of distinct
         reporting laboratories correlate at **r = 0.964** across years: 2019 had 25 labs and 404 findings,
         2025 had 168 labs and 1,959. A bare findings-per-month chart would be read as "medicine is getting
         worse", which this data does not support — so any time series must carry the lab count beside it.
      2. **The archive is a long tail, not a league table.** Median company has **1** finding; **1,521 of
         2,609 (58%) appear exactly once**; the top 10% hold 45.9%. A top-10 bar chart describes 10
         companies out of 2,609 while inviting the verdict CLAUDE.md §6 forbids.
      3. **The two state questions are almost never the same question.** Where both are known they differ in
         **4,999 of 5,391 findings (92.7%)**. West Bengal tests 1,758 findings and makes 103; Himachal makes
         2,147 and tests 104. Two charts, never one map, never summed.
      4. **Categories are mentions, not shares.** 21.8% of findings name more than one failed test (mean
         1.28), so a pie chart would be wrong. And `Spurious: 77 mentions, 0 manufacturers` is the ethics
         invariant **visible in the data itself**.
    - **Gaps the dashboards must disclose:** 101 of 111 calendar months published · 128 findings with no
      manufacturer · 603 of 2,609 manufacturers with no resolvable state · 158 findings missing a date ·
      the pre-portal PDF era is just 132 findings (1.9%).
    - 6 tests (3 unit, 3 integration); `analytics` added to the CI matrix; `ruff.toml` gained a
      notebook rule (E501 only — SQL literals and plotting calls read worse wrapped at 100 characters,
      while unused imports and undefined names are still caught).
- [x] **Step 2 — Superset running, connected to gold through a read-only role** (2026-11-19)
      `apache/superset:6.1.0` in Docker Compose (unlike Airflow, ADR 0012: it is a plain web app with no
      Spark beside it, and it is the one service Phase 12 exposes to the internet). Metadata in a new
      `superset` database beside `drugwatch` and `airflow`; Redis for its four caches; UI on
      **127.0.0.1:8088**, healthy in 18 s.
    - **"Superset reads gold only" is now a Postgres grant, not a convention.** `superset_reader` has
      `SELECT` on `gold` and nothing else (`infra/postgres/superset_reader.sql`, idempotent). Two payoffs:
      a chart accidentally built on `staging.silver_nsq` (pre-quality-gate data) or `ops.pipeline_run`
      (operational internals) **fails** instead of quietly publishing, and a Superset compromise — the
      service most exposed in Phase 12 — cannot write a row or reach the `airflow` database.
    - **`ALTER DEFAULT PRIVILEGES` is the subtle part:** dbt drops and recreates gold tables on every
      build, and a new table carries no grants. Without it Superset would lose access to a mart the next
      time the pipeline ran — an empty dashboard at the worst possible moment.
    - **Verified through Superset itself, not just psql** (`infra/superset/smoke_test.sh`, 6 expectations,
      exit 0): `gold.fact_nsq_sample` → 7,126 · `gold.dim_manufacturer` → 2,609 · `staging` refused ·
      `ops` refused · `dbt_staging` refused · writing to gold refused. A grant only ever checked with
      psql proves nothing about the app: Superset could have been pointed at the `drugwatch` superuser
      and every dashboard would still have worked. The write attempt is refused **twice over** —
      Superset's own "no DML" guard catches it before Postgres is even asked.
    - **The official image ships no Postgres driver at all** — not psycopg2, psycopg, pg8000 or asyncpg
      (checked, not assumed), because Superset speaks to thirty-odd engines and bundling every driver
      would make it enormous. `superset db upgrade` failed with `ModuleNotFoundError: psycopg2`. Fixed
      with `infra/superset/Dockerfile`, and it hides a second trap: **`python` in that image is
      `/app/.venv/bin/python` while `pip` on PATH is the system one**, so a plain
      `pip install psycopg2-binary` would report success and install into a Python Superset never runs.
      The install is aimed at the venv's interpreter with the `uv` already in the image, as root, then
      the user drops back to `superset` — a service exposed to the internet should not run as root.
    - **Connection and verification are scripted, not clicked:** `register_gold_database.sh` (idempotent)
      and `smoke_test.sh`. A connection that exists only because someone filled in a form cannot be
      rebuilt after `docker compose down -v`, and cannot be reviewed. The reader password reaches the
      container through an env var that the container's own shell expands, so it never lands in the
      host's argv where `ps` could see it.
    - **Memory, measured rather than estimated.** RustFS was holding **2.1 GB for 170 MB of stored data**
      — accumulated cache from the many Phase 5 runs; a restart reclaimed it to 153 MB with all 331 raw
      files and 7,126 findings intact. Superset then settled at **213 MB**, far under the 1–1.5 GB I had
      budgeted; all five services together use ~650 MB of the 4.8 GB VM. No memory limits added: an
      untested limit turns a slow service into a crashing one.
    - **Two obligations recorded for Phase 12**, not silenced: `TALISMAN_ENABLED = False` (HTTPS-only
      headers would break the login cookie on localhost) means Superset logs a missing-CSP warning on
      every start — the warning is deliberately left visible, and Phase 12 must set Talisman with a
      Content Security Policy before this is public. `EMBEDDED_SUPERSET` is **off**: a feature flag
      switched on "ready for later" is a feature nobody has tested.
    - Fixed a false positive in `repo-checks.sh`: it could not tell Compose's escaped variable form
      (meaning "leave this for the container's shell") from a real one, so it demanded `.env.example`
      entries for variables that only exist inside the superset-init container.
- [x] **Step 3 — the dashboards, one per slice** (2026-11-20) — all four built from code,
      never clicked, and every chart verified to return data. 20 charts in all.
    - [x] **3a — "Manufacturer reporting"** (2026-11-19) — 6 charts, all verified returning data.
          Provisioned **from code** (`infra/superset/build_manufacturer_dashboard.py`, idempotent): a
          dashboard that exists only because someone filled in forms cannot be rebuilt after
          `docker compose down -v`, reviewed in a diff, or deployed in Phase 12.
        - **Two new dbt marts rather than SQL typed into Superset.** The dashboard needed figures gold
          did not have, and a Superset "virtual dataset" would have hidden untested logic outside dbt,
          outside lineage and outside git:
          `mart_monthly_reporting` (findings per alert month **with the reporting-lab count in the same
          mart**, deliberately — splitting them would make the misleading chart the easier one to build)
          and `mart_manufacturer_report_counts` (how many companies have how many findings). Both
          documented and tested; `dbt build` 6 nodes green.
        - **Every design choice traces to a measured finding** (`docs/analytics-findings.md`):
          the findings bar chart sits **beside** the reporting-laboratories line, because the two
          correlate at r = 0.964 and a findings-only chart reads as falling quality · the ranking is by
          **separate alert months**, not a total or a score, because ten findings in one alert is one
          inspection sweep · the **long-tail distribution sits next to the ranking**, because 58% of
          companies appear exactly once and a top-20 table otherwise reads as "the worst 20".
        - **The disclaimer is on the dashboard now, not deferred to step 5:** a markdown tile carries
          "Not medical advice. Data from CDSCO public alerts.", the one-batch scope, "reporting history,
          not quality", the r = 0.964 explanation, and "not found never means guaranteed safe".
        - **Verified by asking every chart for its data** (`infra/superset/verify_charts.py`, exit 0):
          `Batches reported` 1 row · `per alert month` **101 rows** (the 101 published months) ·
          `laboratories per month` 101 rows · `ranking` 20 rows × 6 columns · `long tail` 15 rows.
          Values spot-checked against the SQL: Jackson Laboratories 49 alert months / 90 reports,
          2026-09 = 330 findings / 48 laboratories, 1,521 companies at one finding (58.3% of companies,
          21.73% of findings).
        - **Two Superset lessons, both found by running it:**
          1. **A chart needs a stored `query_context`, not just `params`.** Superset's UI saves both;
             an API-created chart with only `params` is accepted and then fails anything that asks it
             for data server-side — which in Phase 9 would include alerts and reports. The build script
             now writes the query context for each of the three viz shapes it uses.
          2. **My verification was wrong before the charts were.** `GET /api/v1/chart/{id}/data/`
             rejected them with a bare "400 Bad Request … could not understand", while POSTing the very
             same stored context to `/api/v1/chart/data` returned the right numbers. The verifier now
             does what a dashboard does. Chasing the GET would have meant debugging the test instead of
             the thing under test.
        - `infra/` Python was never linted: the CI matrix is per uv project, and these scripts belong to
          none. CI now runs a pinned `ruff` over `infra/` via `uvx` — 10 findings fixed, all line length.
    - [x] **3b — "Where medicines are made and tested"** (2026-11-19) — 4 charts, all verified.
          The dashboard is deliberately awkward, and the awkwardness is the content: it refuses to
          answer "which state has the worst medicine", because the archive cannot.
        - **The thesis is a live figure, not prose.** `mart_lab_vs_maker_state` computes it on every
          `dbt build`: **4,999 of 5,391 findings where both states are known — 92.7% — were tested in a
          different state from where they were made**, and only **75.7%** of the archive can answer the
          question at all (603 manufacturers have no resolvable state). A number typed into dashboard
          text is right the day it is written and silently wrong afterwards.
        - **Two charts, never one, never summed.** "Made here" and "tested here" are separate charts with
          separate titles, side by side and the same size, so neither can be read alone. The note says
          adding them would double-count the few findings where maker and laboratory share a state and
          misrepresent the other 92.7%. The table gives `state_lab_reports_tested_here` its own column:
          a state laboratory tests its own state's samples, so that — much smaller — number is the only
          honest answer to "what did this state's own testing find?".
        - **No map** (decision D), with both reasons on the page: India's boundary depiction is legally
          sensitive for a public site serving Indian users, and Superset's bundled GeoJSON may predate
          the 2019 Jammu & Kashmir / Ladakh reorganisation and the 2020 Dadra & Nagar Haveli merger. A
          bar chart carries the same information and makes no territorial claim.
        - **Refactored before the duplication could set in:** the second dashboard needed the same
          provisioning pieces as the first, so they moved into `infra/superset/dashboards.py` (datasets,
          metrics, chart creation with its query context, and a `Layout` builder for the grid JSON).
          Each `build_*_dashboard.py` now holds only its charts and the reasoning behind them. Same
          argument as Phase 5's shared `processing_chain()`: copies drift.
        - **A categorical x-axis needed a fix in the shared code:** `query_context()` was setting a time
          grain on every axis, which on a text column (`state_name`) would ask Postgres to truncate a
          string to a month. The grain is now only set for a date axis.
        - **Caught by spot-checking rather than by the row count:** the bars came back in *alphabetical*
          order. The data was right — the 15 rows really were the 15 largest states, Himachal 2,147 down
          to Andhra 59, nothing dropped — but drawn alphabetically the chart hides the shape it exists to
          show. Fixed with `x_axis_sort` naming the metric. **Limitation stated plainly: I verified the
          data each chart returns, not the pixels** — bar order and layout need a human with a browser,
          which is Harith's check.
        - **Verified** (`infra/superset/verify_charts.py`, exit 0): all **10 charts across both
          dashboards** return data. States: made-here top Himachal 2,147 · **tested-here top West Bengal
          1,758**, then Assam 946 and Chandigarh 751 (central laboratories) · the side-by-side table
          carries all 36 states and union territories including the zeros, so a state with nothing
          reported is visible rather than missing.
        - ⚠️ **Corrected 2026-11-20, by Harith looking at the dashboard.** This entry first recorded
          "tested-here top Assam 946 / Chandigarh 751". That was wrong: those were simply the first rows
          the chart *returned*, which arrive alphabetically after the pivot, and I read them as if they
          were the largest. West Bengal (1,758) was on top all along, and the chart had been right since
          the `x_axis_sort` fix. The lesson is the one the step already admitted and then forgot within
          the same entry: **"the data is right" and "I have read it correctly" are different claims**, and
          a row order is not a ranking.
    - [x] **3c — "What kinds of medicine are reported"** (2026-11-20, **ADR 0014**) — 5 charts
          plus the freshness panel, all verified. The only dashboard in the project built on a
          column the archive does not contain, and that shaped every choice on it.
        - **Reviewed by Harith, 2026-11-20: 213 of 215 proposals accepted**, `oxetacaine` and
          `menthol` rejected — both because the ingredient's role changes with what it is combined
          with, so a single class would have mislabelled one of the two uses. Those products stay
          `Unclassified`, which is the outcome the review exists to make available.
        - **80.6% of findings classified (5,744 of 7,126); 1,382 are not**, and `Unclassified` is
          the largest bar on the chart and the first row of the table on purpose. A reader's first
          question about a classification is how much it misses, and sorting it away would have
          been easy and would have flattered the work.
        - **The classes sum to 7,721 against an archive of 7,126**, because 530 findings carry two
          to four classes. So no pie chart anywhere on the page: bars and tables can carry
          "overlapping categories", a pie asserts the opposite.
        - **Two new marts exist so that no chart has to remember a caveat.** §8.2's
          `mart_drug_class_failures` is correct but its grain is class × category × month, where
          one finding can be four rows — `sum(findings)` on a dashboard would silently inflate
          every class. `mart_drug_class_summary` (one row per class) and
          `mart_drug_class_category` (one row per class × category) make the safe reading the
          default one. The headline percentages are repeated columns read with `MAX`, the same
          shape `mart_lab_vs_maker_state` already uses.
        - **The results are pharmacologically coherent, which is the best evidence the vocabulary
          works**: injectable fluids fail *sterility* 68.1% of the time, tablet-form
          antihypertensives fail *dissolution* 53.1%, syrups fail *assay* 64.4%. Nothing in the
          vocabulary knows about dosage forms or failure categories, so that pattern is the data
          agreeing with the lens rather than the lens imposing itself.
        - **Measured first: there is no classification in this archive to read.** `generic_name` is
          filled for 1,340 of 5,651 product names (23.7%) and holds the whole printed string
          (`"Amoxycillin and Potassium Clavulanate Tablets IP"`), not a normalised salt. No ATC
          code, no therapeutic group, nothing. So the class has to come from outside the data,
          which makes it **a claim someone made, not a fact the archive reports** - and the design
          keeps that visible instead of burying it in a column.
        - **215 ingredient phrases match 5,746 of 7,126 findings (80.6%).** The remaining 1,380
          stay `Unclassified` and that number goes on the dashboard: it is mostly brand-named
          products whose pack prints no ingredient (`"Zylinta Syrup"`), which is a real limit of
          name-based classification rather than a bug to tune away.
        - **Phrases, never single words - this is the one that would have gone wrong quietly.** A
          word-level vocabulary files "Atorvastatin Calcium Tablets IP" under mineral supplements,
          because `calcium` there is the salt the statin is formulated as. So salt and mineral
          names appear only as complete phrases (`calcium carbonate`, `ferrous sulphate`, `sodium
          chloride`) and a bare `calcium`, `sodium` or `sulphate` is never in the vocabulary.
          Tested against "Diclofenac Sodium", "Thyroxine Sodium" and "Rabeprazole Sodium": each
          matches only its active ingredient. Whole-word matching too, so `ringer` does not match
          "Ringerol" and `aspirin` does not match "Aspirinox".
        - **A list per product, not one class.** 564 findings (7.9%) contain two to four classes -
          combination products are the norm here ("Ambroxol Hydrochloride, Terbutaline Sulphate,
          Guaiphenesin & Menthol Syrup"). Picking one would need a priority rule nobody can
          defend, so `drug_classes` is an array and **every chart on it must state that the
          classes add to more than the total**. Same contract as `failure_categories` (ADR 0009).
        - **Four of the 26 classes exist to say "this is not a medicine."** CDSCO tests absorbent
          cotton wool (50 findings), gauze, bandages, hypodermic syringes, hand sanitiser (41),
          soap, hair colour, mehandi cones and propylene glycol. They get `Surgical consumable or
          device`, `Antiseptic / disinfectant`, `Cosmetic or toiletry` and `Pharmaceutical raw
          material`. This matters most for the beauty creams: some were tested *because* they
          contained steroids they should not have, so filing them under `Corticosteroid` would
          invert what the finding means.
        - **The review is split the way Phase 3's manufacturer review was.** 187 `CLEAR` entries
          (the class is the ingredient's textbook use, nothing to choose) are offered one batch per
          class, each ingredient printed with its reason, its finding count and a real product
          name. 28 `JUDGEMENT` entries are asked one at a time, each printing **why the proposal
          might be wrong** first: aspirin is a painkiller at full dose and a clot preventer at the
          low dose used here; menthol is a decongestant in a cough syrup and a skin coolant in a
          pain gel; clavulanate is not an antibiotic at all. `n` is a real answer - it leaves those
          products `Unclassified`, which is correct when nobody can say.
        - **Every proposal must carry a reason, and that is enforced, not hoped for.** One test
          rejects a reason under 13 characters; a second rejects a reason that only restates the
          ingredient and its class (`"Vitamin."` under `Vitamin / mineral supplement`,
          `"Bandage."` under `Surgical consumable or device`); a third requires each judgement call
          to state its alternative. **Writing the tests found 13 such reasons in my own first
          draft** - "NSAID.", "Anthelmintic.", "Vitamin." - and they were rewritten rather than the
          threshold lowered. A reason a reviewer cannot disagree with is decoration.
        - 33 tests, all passing. Decision log is git-ignored (`data/drug-class-review/`); the
          accepted vocabulary is committed, because an ingredient's class is published pharmacology
          while the manufacturer mapping holds real CDSCO names (ADR 0003). No archive count goes
          into the seed.
    - [x] **3d — "Spurious (counterfeit) reports"** (2026-11-19) — 4 charts, all verified. The
          archive's smallest slice (77 of 7,126 findings) and its most easily misread, so it is the one
          built with the most care.
        - **The ethics rule is structural, not editorial.** A spurious finding means the *pack* was
          judged fake; the company printed on it is the brand somebody copied, and is the victim of the
          counterfeit (CLAUDE.md §6). So `mart_spurious_report` **carries no `manufacturer_id` at all**
          — verified: 0 of its columns mention a manufacturer — and nothing can attach these findings to
          a company even by a careless join. The copied brand is named `name_printed_on_the_pack`,
          because a column called anything like "company" would eventually be charted as one.
        - **The scale is stated before the charts, and warns against the obvious misreading:** 77
          findings from 2024-04 onwards, single digits in most of 24 months. That makes this a record of
          *what CDSCO published about counterfeits*, not a measure of how much counterfeiting exists —
          and the note asks the reader explicitly not to read the monthly chart as a trend.
        - **Every row keeps its batch number, alert month and CDSCO link**, which is what makes a
          finding checkable by someone holding a pack rather than merely alarming.
        - **Verified** (exit 0): `Every spurious finding` returns **all 77 rows**, with the copied brand
          filled on **17** of them (the alerts simply do not name one on the rest); `dbt build` 74 nodes
          green including a `not_null` test on `source_url`, so a finding can never appear without the
          document that reports it.
        - **All 14 charts across the three dashboards return data.**
- [x] **Step 4 — anonymous read-only access** (2026-11-20)
      16 expectations, all holding (`infra/superset/public_access_test.py`, exit 0). An anonymous
      visitor can open all three dashboards, run every chart's query and change a filter; and cannot
      create a chart, rename or delete a dashboard, run SQL, list database connections, read the role
      configuration, list users, or create a dataset.
    - **`PUBLIC_ROLE_LIKE = "Gamma"` — the shortcut Superset's own docs and most tutorials reach for —
      was rejected after reading what Gamma actually grants on this instance.** Checked, not assumed, it
      includes `can_write on Chart`, `can_write on Dashboard`, `can_delete_embedded on Dashboard`,
      `can_write on Theme` and `can_add`/`can_edit`/`can_delete on UserRegistrationsRestAPI`. Copying it
      into the public role would let **any stranger on the internet create, edit and delete the
      dashboards, and register users.** For the one service Phase 12 exposes, the public role is built
      from nothing instead: **21 permissions, each justified in
      `infra/superset/configure_public_role.py`**, and the refusals are listed in that file too so the
      decision is on the record rather than implied by absence.
    - **Datasource access is granted per dataset, not as "all datasources".** The seven gold datasets are
      named individually, so a dataset added later is invisible to the public until someone grants it —
      the script prints what it granted, and is idempotent (it *removes* anything not on the list, so a
      permission added by hand in the UI does not survive).
    - **The uncomfortable finding, stated rather than hidden: "filters working" requires a write
      permission.** Superset stores a visitor's filter selections server-side and returns a key, so
      `can_write on DashboardFilterStateRestApi` is needed for step 4's done-when to be true at all. It
      writes only transient state for that visitor and cannot touch a chart, a dashboard or any data —
      and it is listed as an explicit exception rather than waved through inside a bundle.
    - **My test lied before Superset did, twice over:**
      1. It reported `can_read on ChartDataRestApi` as a needed permission. No such permission exists in
         this build — the chart-data endpoint is guarded by `can_read on Chart`. The script printed it as
         **NOT FOUND** instead of skipping it silently, which is how it was caught.
      2. It claimed a stranger could **list users** (HTTP 200). urllib was *following* Flask-AppBuilder's
         redirect to `/login/` and reading the login page as success. The endpoint was always protected;
         the test was wrong. It no longer follows redirects, so "you must log in" surfaces as the 302 it
         is. Same lesson as the bar-order correction: a green check is only as good as what it measures.
    - **Checked that routine setup does not undo it:** `superset init` syncs role definitions, so it was
      run again afterwards — the Public role still had exactly 21 permissions, so a future
      `superset-init` cannot quietly reopen the instance.
    - ⚠️ **"Publicly" still means on this machine.** `docs/permissions.md` requires CDSCO permission
      before this data appears on a live site, and **neither permission email has been sent**. Phase 12
      must also enable `TALISMAN_ENABLED` with a Content Security Policy and change the admin password,
      which is currently `admin`.
- [x] **Step 5 — source notes and dashboards as code** (2026-11-20)
    - **Source note on every dashboard, in one place.** `SOURCE_FOOTER` in `dashboards.py` is appended
      to all three notes, so a dashboard added later cannot be missing it: it credits CDSCO, links to
      cdscoonline.gov.in, states that the data is reproduced unaltered and that the CDSCO document is
      authoritative, and explains how the numbers were built. The disclaimer itself went on in step 3a
      rather than waiting for this step.
    - **All three dashboards are now in the repo as YAML** (`infra/superset/assets/`, 26 files: 3
      dashboards, 14 charts, 7 datasets, 1 database, metadata). Until now they existed only in the build
      scripts and Superset's own database, neither of which is a deployable artifact.
      `export_assets.py` **refuses to write if a real credential is in the bundle** — it searches the
      export for `SUPERSET_READER_PASSWORD` before touching the disk. Checked: the exporter masks the
      URI as `superset_reader:XXXXXXXXXX@postgres:5432/drugwatch`, and the real password appears 0
      times. The top-level export directory is stripped, so a re-export is a clean diff rather than a
      new folder.
    - **The deployment path is tested, not assumed** (`import_assets.sh`): the committed YAML is
      re-zipped and imported, then every chart is re-verified. **Superset's importer requires the top
      directory the exporter adds** — without it the import dies mid-JSON-decode with no useful
      message, which is exactly the kind of thing Phase 12 should not discover on a server. The script
      adds it back. Round trip confirmed: export → repo YAML → import → `every chart returned data`,
      and public access unchanged.
    - **The "Data last updated" panel is live on all three dashboards**, showing
      `19 Nov 2026 · 1 day ago · 7,126 findings · 331 source files · quality gate success`. One chart
      reused on all three, not three copies: a reader comparing two pages must never see two different
      answers to "how old is this?". `mart_data_freshness` reads Phase 5's run log through a new dbt
      `ops` source, so **Superset is never granted the `ops` schema** - one curated row crosses the
      boundary instead of the whole operational log - and it reports the latest **successful** run,
      because a failed run leaves the previous data in place and its timestamp would overstate freshness.
    - 🔍 **Root cause of the blocker that stopped this step, found after the first three theories were
      wrong.** Registering the dataset produced a `tables` row that Superset's own API returned 404 for,
      while its uniqueness check still saw it - so the dataset could neither be found nor recreated, and
      all three build scripts crashed. Ruled out in order: Redis cache (flushed), in-process cache
      (container restarted), permissions as usually understood (admin has `all_datasource_access`), and
      the asset re-import. The actual cause:
      **Superset's dataset *and* chart list APIs filter by `datasource_access`, and an admin's
      `all_datasource_access` does not cover a dataset that no role holds a grant for.** Datasets 1-7
      had only ever been visible because step 4's public-role script had granted them. Granting the new
      dataset made it - and its chart - appear instantly.
      Fixed properly rather than worked around: `ensure_dataset()` now catches that 422 and exits with
      the explanation and the exact command to run, so the next person meets a one-line instruction
      instead of a traceback. (Harith approved deleting the corrupt row; it was backed up with `pg_dump`
      first, and the orphaned chart that pointed at it was removed with it.)

**Done when:** dashboards are viewable publicly with filters working.
✅ **Phase 6 signed off by Harith, 2026-11-20.** All five steps done; four dashboards, 20 charts,
every one verified to return data; anonymous read-only access proven by test; the whole thing
exported as YAML and re-imported successfully. The visual review is Harith's and continues to be -
anything that looks wrong on a page is a fix, not a reopened phase.
⚠️ **"Publicly" is local-only until Phase 12:** `docs/permissions.md` requires CDSCO permission before the
data appears on a live site, and **neither permission email has been sent**. Sending them is on the
critical path and is Harith's to do.

---

## Phase 7 — Data Science

Approved 2026-11-20. Plan: `DRUGWATCH_PHASES.md` §9 Phase 7 and §12. Goal: a manufacturer risk
score with per-manufacturer explanations.

**Four decisions taken at the start** (Harith, 2026-11-20 — "your recommendations"):
- **A. scikit-learn is a direct dependency** of `ml/`, for §12's logistic-regression baseline and
  its metrics only — **ADR 0015**. It costs nothing: `shap`, `mlflow` and `skops` already install
  it, so this makes an existing transitive dependency a declared one.
- **B. MLflow runs as a Compose service** with Postgres behind it and RustFS for artifacts —
  **ADR 0016**. Decided by Phase 8, not Phase 7: a serving container cannot read a directory on
  the Mac.
- **C. A stricter bar than the plan's.** LightGBM must beat **all three** baselines on PR-AUC with
  a confidence interval excluding no-difference. The plan says "beats both baselines", which the
  measurements below show could be satisfied by luck against the weakest one.
- **D. Two features the plan does not list**: §12's drug-class shares (unblocked by Phase 6 step
  3c) and the archive-wide testing volume in the window.

**What was measured before planning anything** (2026-11-20, against the live `mart_ml_features`):
- **The real bar is higher than the plan assumes.** §12's baseline 1 ("reported in the last 6
  months → will be again") scores **ROC-AUC 0.623** on the candidate test year. But simply ranking
  companies by `reports_24m` scores **0.687** — better than the plan's own baseline, and free. A
  model that beat only 0.623 would be beating a straw man, hence decision C.
- **The population grows about 9×** across the archive (304 manufacturers with a cutoff row in
  2019, 2,609 in 2026) and the positive rate drifts between 9.4% and 17.8%. So the test set has to
  be the most recent period and the probabilities need a calibration check, not just a ranking
  metric.
- **44% of manufacturers are invisible to this model by construction.** 1,151 of 2,609 companies
  were first reported *during* the candidate test window, and a company has no cutoff rows before
  its first finding. So the score answers "will a manufacturer **already in the archive** be
  reported again?" and cannot answer "is this company risky?" — a limitation for the model card,
  not a bug.
- **An assumption of mine was wrong, and the data corrected it.** I expected companies with
  nothing reported in 24 months to be near-certain negatives. They are **8.1% positive** against
  19.6% for recently-reported ones — low, but nothing like zero, and 557 of the test window's 3,534
  positives come from that group. They stay in the data and results are reported for both groups
  separately.

- [x] **Step 0 — the `ml/` project and the tracking server** (2026-11-20)
    - **`ml/` reads `gold.mart_ml_features` and nothing else**, in a read-only transaction, so no
      training run can modify the warehouse it learns from. Tested by attempting a write and
      requiring `ReadOnlySqlTransaction`. The connection code is duplicated from `analytics/`
      rather than imported: a training pipeline that breaks when a notebook dependency changes
      would be the wrong coupling.
    - **The feature list is written out, not inferred from the table.** `FEATURE_COLUMNS` names all
      17, and an integration test compares it against the live mart and fails if they differ. The
      failure it prevents is silent: a renamed mart column would otherwise reach LightGBM as a
      column of nulls, train without complaining, and score every manufacturer on a feature that
      means nothing. Tests also pin that the label and the keys are **not** features —
      `as_of_month` as a feature would let the model learn "later months are riskier", which is a
      fact about CDSCO's publishing volume, not about any manufacturer.
    - **The unknowable labels are reachable but never mixed in.** The last 6 cutoffs have a future
      the archive cannot see; those rows keep a null label and nothing fills it in, because an
      unknown future is not a negative outcome. They are exactly the rows that scoring a company
      *today* needs, so both sets are available and a test asserts the null stays null.
    - **Every MLflow run records what it would take to reproduce it**: the git commit, **whether
      the working tree was dirty** (a commit hash describes the code only if nothing was edited on
      top of it), and a fingerprint of the feature table — row count, column count, newest cutoff.
      Deliberately not a hash of the values: the mart is rebuilt monthly and a hash would change
      every time without saying what changed.
    - **Verified end to end before any modelling exists** (`drugwatch_ml.smoke_test`): 71,354
      labelled rows readable, all 17 features numeric, writes refused, a run tagged, and **an
      artifact written to RustFS and read back byte for byte**. That last check earns its place —
      `log_artifact` reports success whether or not the server can reach its artifact store, so a
      misconfigured bucket would have surfaced in Phase 8 as a model that cannot be loaded.
      Confirmed independently against RustFS: `s3://mlflow/1/<run>/artifacts/smoke.json`, 64 bytes.
    - Three things the official MLflow image needed, all found by running it: no Postgres driver
      and no S3 client (added, pinned); no environment variable for RustFS's required path-style
      addressing, so it is baked into the image where it actually applies; and no `ENTRYPOINT`
      with `CMD python3`, so Compose's arguments were being handed to the interpreter.
    - 16 tests passing.
- [x] **Step 1 — the train/validate/test protocol, with an embargo** (2026-11-20)
    - **The leak a normal date split hides, and the reason this step exists.** Every row is a
      manufacturer at a monthly cutoff; its features use months up to the cutoff, but its label is
      a fact about the **6 months after** it. So training to 2025-03 and testing from 2025-04
      shares five of the six months the test is scored on — the model is tested on a future it was
      partly told about. Splitting on the cutoff date alone looks completely clean and shows
      nothing. The fix is to purge the cutoffs in between: `Fold` **refuses to exist** if the gap
      is smaller than the label horizon, and its message names the date to move to, so the guard
      cannot be forgotten by a caller.
    - **The protocol**, built backwards from the newest answerable cutoff (2026-03):

      | | train up to | embargo | evaluate |
      |---|---|---|---|
      | validate-1 | 2022-10 | 5 months | 2023-04..2023-09 |
      | validate-2 | 2023-04 | 5 months | 2023-10..2024-03 |
      | validate-3 | 2023-10 | 5 months | 2024-04..2024-09 |
      | **test** (once) | **2024-10** | 5 months | **2025-04..2026-03** |

      Rolling origin, oldest first, each fold training on more data than the last — which is what
      actually happens in production. All three tuning folds end before the test fold's own
      training cutoff, so nothing that chooses a hyperparameter has seen a month the test is
      scored on. Same rule CLAUDE.md §5 sets for the LLM eval set: a test set you fit against is a
      training set with a flattering name.
    - **The final fit recovers what tuning held back.** After the settings are chosen the model
      refits on everything up to 2024-10 — 42,722 rows, 1,171 companies, 12.8% positive. Those
      months were withheld to choose hyperparameters, not because they are tainted, and dropping a
      year of the most recent data from the final fit would be a self-inflicted handicap.
    - **The embargo costs 6,562 rows (9.2% of the labelled data), and that number is printed**
      rather than left as a design detail. Paying it is the point.
    - 🔍 **Measured, and it changes how step 5 must report: 1,071 of the 2,242 companies in the
      test set (48%) never appear in training at all.** A company gets cutoff rows only from its
      first finding onwards, so the test window is nearly half first-timers — 8,018 rows, 14.6%
      positive, against 16.8% for the 1,171 companies the model trained on. They are still
      scoreable (their features are their own history), but a single headline metric would average
      over "a company the model has watched for years" and "one it is seeing for the first time".
      Step 5 reports both. This is also the concrete form of the limitation for the model card.
    - 42 tests. The ones that matter assert on **label windows, not dates** — they would pass if
      the embargo were deleted, had they been written against dates. Plus two integration tests
      pinning the protocol's shape to the live mart, so a rebuilt mart that shifts the test window
      fails here rather than in a model comparison months later.
- [x] **Step 2 — the feature matrix: 17 features to 28** (2026-11-20)
    - **Decision D's drug-class shares, now that Phase 6 made them possible.** Plan §12 asked for
      "share of reports by drug class"; Phase 4 left it out because nothing classified a medicine.
      ADR 0014's vocabulary unblocked it. Shares of class **mentions**, so they do not sum to 1 —
      a combination product belongs to two to four classes — the same contract as the failure
      categories. Only the **seven classes above 5%** of the archive get a column, plus
      `unclassified_share_12m`: a share of a 2%-class over one company's 12-month window is almost
      always exactly 0 or exactly 1, which is noise with a column name. `distinct_drug_classes_12m`
      is carried instead for the thin tail, because it does not fall apart on small windows.
    - 🔍 **Decision D's other feature was changed by measuring it, and this is the interesting
      part.** I had proposed "how much CDSCO tested overall in this window", so the model could
      tell a company getting worse from the archive growing. Measured: the archive's trailing
      12-month volume correlates **0.855 with calendar time** (2 findings in the earliest window,
      2,517 in the largest). That is not a feature, it is a clock — and because the test period is
      strictly later than training, "recent means positive" would score well for the wrong reason
      and would surface in SHAP as a real risk factor. Tree models cannot extrapolate, so it would
      not even fail loudly; it would just saturate. So it enters **only as a ratio**,
      `share_of_archive_reports_12m`, which keeps the normalisation and drops the timeline:
      **0.855 → -0.180**.
    - **A test now rejects any feature correlating above 0.7 with the cutoff**, and pins the one
      feature in between so a new drifter cannot appear unnoticed. That found a **pre-existing**
      Phase 4 feature: `central_lab_share_12m` at **-0.534**. Real, not a bug — state drug-testing
      laboratories grew relative to CDSCO's central ones across the archive, so the central share
      of anybody's reports falls over time. Kept, because it is still genuinely about which
      laboratories tested *this company's* products, with a model-card note to check SHAP for
      over-reliance on it.
    - 🐛 **A bug I wrote, and the test class that now catches it.** The unclassified share was
      `filter (where drug_class = 'Unclassified')`, which counted **zero of 1,382 unclassified
      findings** — because `dim_drug.drug_classes` holds an **empty array** when the vocabulary
      matches nothing, deliberately (ADR 0014), not the string. The column built, every range
      check passed, and the feature was a constant 0. A constant feature is the worst kind of
      broken one: the model trains on it happily and SHAP calls it unimportant, which is true and
      tells nobody it is empty. Now guarded twice — `assert_ml_feature_shares_are_valid` fails on
      any share that never rises above zero, and a Python test fails on any feature with one
      distinct value. Correct value: 0.222 average, matching the archive's 19.4%.
    - 🐛 **And a bug in that new test, worth recording because SQL invites it.** The null-state
      branch was `(class_mentions_12m > 0) is distinct from (share is not null)`. The counts are
      NULL — not 0 — when a window holds no findings, and `NULL > 0` is NULL, which
      `is distinct from false` reports as TRUE. It flagged all **46,296** quiet rows as corrupt
      data. The mart was right; the test was wrong. `coalesce` added, with the reason in the file.
    - `dbt build` 94 nodes green, 44 ml tests passing.
- [x] **Step 3 — three baselines, and the bar is not where the plan put it** (2026-11-20)
      Measured on the tuning folds only; the test window stays untouched until step 5.

      | baseline | ROC-AUC | PR-AUC | P@20/month |
      |---|---|---|---|
      | §12's rule: reported in last 6m | 0.628 | 0.185 | 0.272 |
      | ranking by reports in last 24m | 0.728 | 0.323 | 0.672 |
      | **§12's logistic regression** | 0.726 | **0.373** | 0.697 |

    - **The bar is PR-AUC 0.373, double the plan's rule at 0.185.** Decision C's worry is now a
      measurement: a model could "beat both baselines" while being far worse than a one-column
      count. And the count ranking really is a serious baseline — ROC-AUC 0.728, *higher* than the
      logistic model's 0.726, with no fitting at all.
    - **Which is exactly why PR-AUC decides and not ROC-AUC.** The two strongest baselines are
      tied on ROC-AUC (0.728 vs 0.726) and clearly apart on PR-AUC (0.323 vs 0.373). With 12-13%
      positives, ROC-AUC is dominated by how well the model orders the easy negatives; PR-AUC only
      cares about the top of the list, which is the part anybody would act on.
    - **The bar was itself tested for significance, not assumed.** Logistic minus count-ranking on
      validate-3: **+0.034 PR-AUC, 95% CI +0.012..+0.050** — excludes zero, so the bar is genuinely
      the logistic model's. Decision C's rule applied to the baselines too; otherwise the bar
      itself could have been a coin flip.
    - **Confidence intervals resample companies, not rows**, and a test proves the grouping
      changes the answer: one manufacturer contributes up to 12 monthly rows, which are one
      company's history seen twelve times rather than twelve independent cases. Row-level
      resampling gives a visibly narrower interval — which is how a model gets reported
      "significantly better" when it is not.
    - **Precision@K is per month, then averaged**, with a test showing it differs from pooling
      (1.000 pooled vs 0.625 per-month on a constructed case). Pooled, the busiest month fills the
      whole top 20 and the quiet months are never represented — but a list is read one month at a
      time.
    - **What the linear model leaned on** (scaled, so comparable): `reports_24m` +0.670, then
      `distinct_reporting_states_12m` +0.306, `central_lab_reports_12m` **-0.298**,
      `distinct_drugs_12m` +0.281, `distinct_drug_classes_12m` +0.208. Breadth of exposure matters
      beyond raw count, and step 6 can check SHAP against this.
    - Leak checks on the only fitted baseline: nulls are filled with the **training** median
      (filling an evaluation set from its own median leaks, invisibly), a column entirely null in
      training becomes 0 rather than reaching sklearn as NaN, and scoring before fitting is
      refused. Filled with pandas, not sklearn's imputer — ADR 0015 approved three classes and a
      fourth would be a wider dependency than agreed for two lines of `fillna`.
    - 66 tests passing.
- [x] **Step 4 — LightGBM, tuned on the validation folds only** (2026-11-20)
      40-trial random search, trial 1 being LightGBM's own defaults so the result can be reported
      as "better than out of the box" and not only "better than other random guesses".

      | | PR-AUC (mean of 3 tuning folds) |
      |---|---|
      | LightGBM **out of the box** | 0.359 |
      | best baseline (logistic regression) | 0.373 |
      | LightGBM **tuned** | **0.383** |

    - ⚠️ **Out of the box, LightGBM loses to logistic regression** (0.359 against 0.373). That is
      worth stating plainly: the mandated model is not automatically the better one here, and
      without tuning this phase would have failed its own bar.
    - ⚠️ **Tuned, it clears the bar — but narrowly.** On validate-3 the margin over logistic
      regression is **+0.033 PR-AUC, 95% CI +0.006..+0.060**. It excludes zero, so decision C is
      satisfied on validation, but a lower bound of +0.006 is a slim win and will be reported that
      way. The test window decides, once, in step 5.
    - 🔍 **The winning settings are far SIMPLER than the defaults**, which is itself the finding:
      `num_leaves` 7 (default 31), `n_estimators` 100 (default 300), `min_child_samples` 100
      (default 20), `lambda_l2` 10, `bagging_fraction` 0.7. Every chosen value points the same way
      — this dataset supports a small, heavily regularised model, and the trials that grew the
      model got worse (the 800-tree, 127-leaf trial scored 0.289). 40,000 rows of monthly
      manufacturer history is simply not much signal, and the search found that rather than being
      told it.
    - **`scale_pos_weight` 3.0 was chosen**, which lifts ranking and distorts the predicted
      probability — exactly the trade-off `model.py` flagged before the search ran. §4.3 shows this
      number publicly as a probability, so **step 5's calibration check now decides whether it may
      be called one**, or whether it must be presented as a rank.
    - **26 of 28 features are split on.** Top gains: `reports_24m` (18,851, dominant, matching
      logistic's +0.670 weight), `distinct_reporting_states_12m`, `months_since_last_report`, then
      **`share_of_archive_reports_12m`** — step 2's ratio replacement for the calendar feature is
      being used, so the normalisation was worth keeping once the clock was removed. Never split
      on: `state_lab_reports_12m` and — reassuringly — **`central_lab_share_12m`, the -0.534
      calendar drifter**. The model declined the feature most likely to be a timeline.
    - **No early stopping during tuning**, on purpose: it would read each fold's own evaluation
      rows to pick the tree count, and those same rows then score the trial. `n_estimators` is a
      searched parameter instead, so the validation folds do exactly one job.
    - 🐛 **A two-hour debugging detour that was my own process failure, not a code bug.** The first
      search ran 141 minutes for 23 trials — 368s each against a measured 3.7s for the defaults.
      MLflow's per-trial runs showed the fits themselves totalled 11 seconds, so the time was in
      the *gaps*: median 8.7s but individual gaps of 1,000 and 3,214s with almost no CPU. **The Mac
      was asleep.** Not a pathological hyperparameter combination — I checked that first and could
      not reproduce it (`num_leaves=127` with `scale_pos_weight=3.0` is 1.5s in isolation).
      CLAUDE.md §10 already says to wrap long local jobs in `caffeinate -i`; I had not. Re-run
      under `caffeinate`, all 40 trials finished in minutes. Recorded because the lesson is that
      "the code is slow" and "the machine stopped running it" look identical from a wall clock.
    - 84 tests passing. `ruff.toml` gained `S311` for test files, beside the existing `S101`: a
      seeded `random.Random` is the point of a reproducibility test, not a weak cipher.
- [x] **Step 5 — the test window, scored once. ⚠️ The result is a partial FAIL** (2026-11-20)

      | model | ROC-AUC | PR-AUC | P@20/month |
      |---|---|---|---|
      | **LightGBM (tuned, calibrated)** | **0.706** | **0.385** | 0.738 |
      | §12's logistic regression | 0.693 | 0.373 | **0.754** |
      | ranking by reports in last 24m | 0.687 | 0.324 | 0.638 |
      | §12's rule: reported in last 6m | 0.623 | 0.214 | 0.337 |

    - ⚠️ **LightGBM does not clear decision C's bar.** Against the rule: +0.171 PR-AUC (CI
      +0.144..+0.201) ✅. Against the count ranking: +0.061 (CI +0.045..+0.075) ✅. Against
      **logistic regression: +0.011, 95% CI -0.004..+0.026 — the interval includes zero.** On this
      test window LightGBM and a linear model are statistically indistinguishable.
    - **And on the metric closest to how the output is used, logistic is ahead**: precision@20 per
      month 0.754 against LightGBM's 0.738. That is the number a monthly list would be judged by.
    - **Reported as-is, exactly as pre-committed.** The step 4 plan said "if LightGBM does not
      clearly win, that is the reported result — the test window is used once and is never tuned
      against." It was used once. There has been no second look, no re-tuning, and no quiet
      widening of the bar.
    - **On the plan's own literal wording it passes** (§9 Phase 7: "beats both baselines" — 0.385 >
      0.373 and > 0.214 on point estimates). It is **decision C**, the stricter bar Harith approved
      on 2026-11-20, that it fails. The bar was raised deliberately because the plan's two
      baselines turned out to be beatable by a `count(*)`; that stricter bar has now done its job,
      which is to stop a 0.011 difference being announced as a win.
    - **The score IS publishable as a probability.** ECE 0.024, mean prediction 0.136 against a
      base rate of 0.160, and the reliability table is monotonic across all ten deciles (top
      decile: predicted 0.458, observed 0.486). **This came from a decision taken on validation,
      before the test was touched**: step 4's search chose `scale_pos_weight` 3.0, whose mean
      prediction was 0.252 against a 0.126 base rate — it doubled every probability. The standing
      rule was "if dropping the reweighting costs less than 0.01 PR-AUC, drop it", because a score
      reading "25% chance" when it means 12% is wrong in a way no caveat repairs. It cost 0.004
      (ECE 0.126 → 0.025).
    - ⚠️ **Every decile under-predicts** (all ten gaps negative). Not a bug: the model trained on
      cutoffs with a 12.8% positive rate and was tested on 16.0%. The base rate drifted upward
      between the two periods, so the model is systematically a little cautious — worth stating
      wherever the number is shown, and worth a monthly recalibration in Phase 9 rather than a
      refit.
    - 🔍 **The 48% finding from step 1 is confirmed and it is large.** Companies seen during
      training: PR-AUC **0.438**. Companies new since training: PR-AUC **0.269**, precision@20
      0.408 against 0.725. The model is far weaker on the half of the archive it has never seen,
      which is the single most important sentence for the model card.
    - **No month is a disaster and the trend is upward**: worst 2025-06 at PR-AUC 0.302, best
      2026-03 at 0.448, rising steadily as each company accumulates history. A single mean would
      have hidden both ends.
    - 🐛 MLflow rejects metric names containing parentheses, and does so *mid-run* after the first
      metrics are already written — so "LightGBM (tuned, calibrated)" killed the first evaluation
      pass between two logging calls. Metric names are now sanitised before they are sent.
- [x] **Decision: option A** (Harith, 2026-11-20) — ship LightGBM, and let the model card say in
      plain words that it is statistically tied with logistic regression. The stack mandates
      LightGBM (plan §6), the point estimates lead on two of three metrics, SHAP comes free from a
      tree model, and a documented negative result is a better artefact than a win nobody checked.
- [x] **Step 6 — SHAP, with the wording rules enforced by tests** (2026-11-20)
    - **Additivity is checked before anything is published, not assumed.** Measured error
      **2.9 × 10⁻¹⁵** over 3,000 rows. `publish` refuses to register a model whose contributions do
      not reconstruct its own predictions, because a silent mismatch would mean the sentences
      describe a different prediction from the one on screen.
    - **Global importance confirms both of step 2's judgement calls were right.**
      `reports_24m` 0.397, `months_since_last_report` 0.272, then
      **`distinct_drug_classes_12m` 0.093** — Phase 6's drug-class vocabulary is the third most
      used signal — and **`share_of_archive_reports_12m` 0.084**, the ratio that replaced the
      0.855-correlated calendar feature. Neither was an obvious win when added; both earned a place.
      `central_lab_share_12m`, the -0.534 drifter, is used **not at all**.
    - **The public wording is a fixed vocabulary of 28 phrases, one per feature, reviewable in one
      screen.** A feature with no approved phrase **raises rather than falling back to its column
      name** — so no future feature can reach a sentence about a named Indian company before a
      person has written neutral words for it. This is the mechanism that implements CLAUDE.md §6
      instead of relying on care.
    - **Five tests enforce the ethics rather than documenting them**: no phrase may contain any of
      17 forbidden words (fraud, fake, counterfeit, unsafe, substandard, offender, blacklist,
      avoid…); no phrase may mention quality; every phrase must describe batches, tests, products
      or laboratories rather than the company; every explanation must end with the
      reporting-history clause; and the direction words are "raises"/"lowers", never
      "worsens"/"improves" — the score is not a grade.
    - The clause lives **in the generated text, not in a page template**, so a website redesign
      cannot drop it.
- [x] **Step 7 — registered in MLflow** (2026-11-20)
    - `manufacturer-risk` version 1, alias `production`. The **plain LightGBM model** is what is
      registered, not an ONNX export: Phase 8 converts it for serving, but `/explain` needs SHAP
      and SHAP needs the tree structure ONNX discards. One artifact serves both.
    - **The test results and the limitations are tags on the registered version**, not only on a
      run. A model in a registry outlives the conversation that made it, so whoever loads it in
      Phase 8 reads "statistically tied with logistic regression" off the artifact itself:
      `test_pr_auc 0.3846`, `test_roc_auc 0.7062`, `test_expected_calibration_error 0.0242`,
      `test_window 2025-04..2026-03`, and a `limitations` tag naming the tie, the 0.269-vs-0.438
      gap and the under-prediction.
    - Artifacts logged: the SHAP importance plot and CSV, and three worked explanations spanning
      the score range. **No manufacturer is named in them** — a worked example naming a real
      company is a published allegation (ADR 0003).
    - `get_latest_versions` is deprecated with registry stages; replaced with
      `search_model_versions`.
- [x] **Step 8 — `docs/model-card.md`** (2026-11-20) — 185 lines, written for whoever ships or
      reviews this rather than for us. Leads with what the score does **not** predict, states the
      tie with logistic regression under its own heading, gives the seen/new split as a table,
      explains why PR-AUC is the headline (a random ranking scores 0.16 here, not 0.5), lists the
      §12 features that cannot exist and why, and ends with eight numbered limitations and the
      unsent permission emails.

**Done when:** LightGBM beats both baselines on the time-based test set, and explanations are
generated. ⚠️ Raised by decision C to **all three** baselines, on PR-AUC, with a confidence
interval that excludes no difference. **If LightGBM does not clearly win, that is the reported
result** — the test window is used once and is never tuned against.

**Outcome (2026-11-20): met on the plan's criterion, NOT met on decision C's.** On point estimates
LightGBM beats both of §12's baselines (PR-AUC 0.385 against 0.373 and 0.214). Under decision C it
beats the rule and the count ranking with intervals clear of zero, and is **tied with logistic
regression** (+0.011, 95% CI -0.004..+0.026). Explanations are generated and their arithmetic is
verified. Shipped under option A with the tie documented on the registered model and in the model
card. The stricter bar did exactly what it was raised to do: it stopped a 0.011 difference being
reported as a win.

---

## Phase 8 — Model Serving

Approved 2026-11-21. Plan: `DRUGWATCH_PHASES.md` §9 Phase 8. Goal: fast, portable predictions.
**ADR 0017** records the architecture.

- [x] **Steps 1-2 — ONNX export, verified with a veto** (2026-11-21)
    - **Measured on the real test window, not on random numbers** (which exercise leaves no
      manufacturer ever reaches): 22,070 rows, **max difference 1.37 × 10⁻⁷**, mean 3.07 × 10⁻⁸,
      Spearman **1.000000**, **0 inverted rows**, identical top-20. ONNX runs tree ensembles in
      float32 while LightGBM accumulates in float64, so they cannot agree to the last bit; what
      matters is whether the gap could move anything a reader sees, and 1.37 × 10⁻⁷ cannot.
    - `build_onnx` **deletes the artifact and exits non-zero** if the comparison fails. A served
      score has to be the score the model card describes.
    - 🐛 **My first verification check was wrong, and it failed loudly in the right direction.** It
      compared `argsort` outputs and reported a changed ranking at **zero** real inversions with
      Spearman 1.000000. Where the original gives two rows exactly equal scores, a stable sort keeps
      input order while a 1e-8 difference in the converted model orders them — so the check was
      measuring tie-breaking. Replaced with a count of rows that moved below something the original
      ranked **strictly** beneath, plus whether the **top-20 set** changed, which is what
      precision@20 actually depends on.
    - The ONNX artifact is **not committed**: a binary derived from a tracked model version is not
      a source file, and it is rebuilt from the registry.
- [x] **Step 3 — `/health`, `/predict`, `/explain`** (2026-11-21)
    - **`/predict` answers from ONNX, `/explain` computes SHAP over the original model and returns
      the ONNX score**, so the number in an explanation is always the number `/predict` gives for
      the same row. **Startup refuses to serve if the two disagree** by more than 5 × 10⁻⁴ — half
      the smallest unit anyone will see, because a score shown as "14.2%" cannot be moved by less.
      Measured at startup: 2.6 × 10⁻⁸.
    - ONNX stores an inference graph — thresholds, child pointers, leaf values — and SHAP needs the
      node coverage that graph discards. So an ONNX-only service could score and not explain, and
      §4.3 requires it to do both. That is the whole reason both representations are loaded.
    - **The service never touches Postgres.** Phase 9's Spring Boot API reads `gold` (plan §5) and
      posts the 28 features. Credentials here would mean a prediction endpoint that shares the
      warehouse's failure modes, and a second place a password can leak. **A test reads
      `docker-compose.yml` and fails if `POSTGRES_*` or `RUSTFS_*` ever appear in its environment**
      — an architectural promise with nothing checking it is a comment.
    - **A missing feature is a 422 naming it; an unexpected feature is also a 422.** Several
      features are legitimately null — a share is null when the window held no findings to divide —
      so null is a *value* the model was trained to read. Filling an absent field with 0 would
      answer a different question and say nothing about having done so. Column **order comes from
      the model**, never from the request: JSON objects have no meaningful order, and a caller that
      serialised its fields differently would otherwise have every value shifted into the wrong
      feature and still get a plausible-looking 200.
    - **`/health` serves the model's own limitations**, read from the tags Phase 7 attached to the
      registered version — so a disputed score is traceable to a version and the caveat comes off
      the artifact rather than a hardcoded string.
    - **The approved wording is imported from `drugwatch_ml.explain`, not copied.** A second copy
      of public text about named Indian companies is a second thing to keep correct, and the copy
      is the one that drifts. That makes `drugwatch-ml` a runtime dependency — a deliberate
      coupling, and the honest cost is a 2.44 GB image (265 MiB resident).
- [x] **Step 4 — containerised** (2026-11-21)
    - 🐛 **MLflow 3 blocked the container on arrival.** It rejects an unrecognised `Host` header as
      DNS-rebinding protection, and its default list is localhost plus private IPs — which does
      **not** include a compose service name. `risk-api` calling `http://mlflow:5000` got a 403
      "possible DNS rebinding attack". Fixed by naming the hosts explicitly rather than disabling
      the protection, which is worth keeping for a service Phase 12 may expose.
    - 🐛 **And then I broke host access with the fix**: listing only `:5000` meant every command run
      from the Mac — which reaches the published `:5050` — got the same 403. The deployment tests
      caught it within one run. Both ports are now listed, with the reason in the compose file.
    - 🐛 **The container needs `libgomp1`**, LightGBM's OpenMP runtime, or `import lightgbm` fails
      at start with `libgomp.so.1: cannot open shared object file` — which reads like a Python
      packaging fault and is not one. It is the same dependency `brew install libomp` provides.
    - `--frozen` and `--no-dev`: no pytest or ruff in a deployed image, and a build that cannot
      re-resolve, because a container that resolves is one whose dependencies can change between
      two builds of the same commit. Non-root user. One uvicorn worker, because each worker loads
      its own model and its own SHAP explainer.
    - 🔍 **MLflow's footprint dwarfs the service's**: ~1.87 GiB resident against the risk service's
      ~265 MiB, on a 4.8 GiB Docker VM. It starts **four** workers by default; pinning it to one
      moved it from ~1.93 GiB to ~1.74 GiB — so most of that is a single process's import baseline
      rather than the worker count, and it is recorded as the modest saving it is. Worth knowing
      before Phase 12 sizes a VM.
- [x] **Step 5 — latency recorded** (2026-11-21) — full table and reasoning in
      **`docs/benchmarks.md` §2**. 1,000 requests per endpoint, at a 1-minute load average of 1.74.

      | | p50 | p95 | p99 |
      |---|---|---|---|
      | `/health` | 1.1 ms | 2.4 ms | 4.3 ms |
      | `/predict`, 1 row | 3.8 ms | 6.1 ms | 11.9 ms |
      | `/predict`, 100 rows in one call | 7.3 ms | 24.8 ms | 32.4 ms |
      | `/explain`, 1 row | 5.7 ms | 9.9 ms | 16.3 ms |
      | `/predict`, 8 concurrent | 9.9 ms | 19.6 ms | 30.5 ms |
      | `/explain`, 8 concurrent | 20.3 ms | 30.3 ms | 38.4 ms |

      No request failed at any concurrency.
    - 🔍 **A batch is 51× cheaper per row**: 3.8 ms for one row alone against **0.07 ms per row**
      inside a 100-row call, because at 100 trees of 7 leaves almost none of the time is the model
      — it is HTTP, JSON and one ONNX invocation. **Phase 9 should send one batch per page.** A
      20-company page costs ~76 ms of round trips done singly and ~5 ms done together.
    - **An explanation costs only 1.9 ms more than a score**, which is a direct dividend of step
      4's finding that the data supports a *small* model. The 127-leaf, 800-tree candidate would
      have made `/explain` an order of magnitude slower **and** scored worse (PR-AUC 0.289).
    - ⚠️ **These are not server numbers, and the write-up says so.** p50 and p95 held steady across
      three runs; p99 on the same endpoint moved between 29 ms and 371 ms with no code change.
      Taken immediately after a 2.4 GB image build, the same benchmark reported a p99 of
      **2,426 ms** for an endpoint whose p50 was 17 ms — it was measuring the build. The final run
      waited for the machine to go quiet, and the reproduction instructions say to do the same.

**Done when:** service runs in Docker, outputs match the original model, latency recorded.

**Outcome (2026-11-21): all three met.** The service is healthy in Docker at ~265 MiB resident;
the ONNX export matches the original on 22,070 real rows with 0 inverted rows and an identical
top-20; latency is recorded in `docs/benchmarks.md` §2 with its measurement caveats stated.
✅ **Phase 8 signed off by Harith, 2026-11-21.**

---

## Phase 9 — Backend

Approved 2026-11-21. Plan: `DRUGWATCH_PHASES.md` §9 Phase 9, §10 (endpoints), §8.3 (app tables).
Goal: the main application API. The project's first Java, so each step introduces its tools.

**Five decisions taken at the start** (Harith, 2026-11-21 — "your recommendations"):
- **A. Maven + Spotless + ArchUnit, and no coverage gate** — **ADR 0018**. ArchUnit enforces the
  plan's layering as a test. JaCoCo's 80% gate is deliberately left out: a percentage measures
  which lines ran, not which behaviours were checked, and the tests that have actually paid for
  themselves in this project would mostly not have moved it.
- **B. `pg_trgm` for fuzzy drug search**, built as a dbt index since dbt owns `gold`. The
  extension ships inside the Postgres image; the alternative was hand-written fuzzy matching over
  5,651 names in Java.
- **C. Rate limiting with a small Redis counter** rather than adding Bucket4j — Redis is already
  in the stack and the counter is ~30 lines.
- **D. The watchlist watches a search term, not one exact product**, and the API polls daily for
  an un-notified alert month rather than Airflow calling it. Phase 4 deliberately did not merge
  the 5,651 printed product names, so an exact-product watch would silently miss the same medicine
  printed differently — and for someone watching their own medicine, a missed alert is worse than
  an extra email.
- **E. Email verification before any watchlist email** (beyond the plan). Without it, anyone can
  register with a stranger's address and the site emails that stranger about medicine alerts under
  CDSCO's name. One column and one link.

**Measured before planning** (2026-11-21, against the live `gold`):
- **40% of batch numbers carry spaces or punctuation** (2,841 of 7,126): `KA/018`, `TETY-01`. So
  both sides of a batch comparison are normalised, or a user typing `KA018` finds nothing.
- **…but normalising must not over-merge**: stripping punctuation collapses 6,807 distinct values
  to 6,766, and leading zeros stay significant (`01` ≠ `1`). CLAUDE.md §5's "a missed merge is
  better than a wrong merge" applies to batch numbers too.
- **A sentinel hides in the data**: `"Not applicable"` is the batch number on 22 findings and must
  never match a user's search.
- **Very short batch numbers exist** (`1`, `6`, `01`), which is why §4.1's batch checker requires
  a medicine name *and* a batch, never a batch alone.
- `pg_trgm` is **not installed** in the Postgres image's database yet (decision B adds it).

**Already settled:** `/api/v1/prices/compare` (§10) **will not be built**. Phase 6's decision A
found no price data anywhere downstream of `raw/`, and an endpoint cannot serve data that does not
exist. It belongs to the deferred price phase.

- [x] **Step 0 — the skeleton** (2026-11-21)
    - **Spring Boot 4.2.0 on Java 21**, built with Maven 3.10.0 pinned by `./mvnw`. 🔍 **The
      version nearly came out a whole major release stale**: Maven Central's *search API* answers
      `3.5.3` for `spring-boot-starter-parent`, while its own `maven-metadata.xml` says **4.2.0**.
      Same class of error as Phase 7's `boto3==1.41.9` pin, which never existed — a plausible
      version number is not a checked one.
    - **Packages are organised by feature, with the plan's layering inside each.** A top-level
      split into `controllers/`, `services/` and `repositories/` puts the three files that change
      together in three different places.
    - **The layering is enforced by ArchUnit**, not by convention: a controller may not depend on
      a repository, a repository may not depend on the layers above it, and only the entry point
      may sit in the root package. Same instinct as the dbt test that refuses an unreviewed drug
      class and the test that reads `docker-compose.yml` for stray credentials.
    - **Actuator exposes health and nothing else, with no component detail.** Left at its defaults
      it publishes configuration, environment variables and a map of every internal service with
      its state — and this is the service Phase 12 exposes. Three tests check it: health answers,
      `components` is absent, and `/actuator/env` and `/actuator/beans` return 404.
    - **CI gained a `backend` job** running `./mvnw verify` on Temurin 21 with a Maven cache, in
      parallel with the Python jobs. `ml` and `ml-serving` were also added to the Python matrix —
      both had been building and testing only on this Mac. Verified they pass with no credentials
      (91 and 40 tests, integration ones skipping cleanly), which is what CI will see.
    - 🐛 Four things Spring Boot 4 changed that cost a build each: an XML comment may not contain
      `--` (my `ruff format --check` aside broke the POM); **ArchUnit fails a rule that matched no
      classes**, which is right and needed a documented allowance while the skeleton has no
      controllers; **`TestRestTemplate` no longer exists** (replaced by `RestTestClient`); and
      `RestTestClient` needs both `@AutoConfigureRestTestClient` **and** a separate
      `spring-boot-resttestclient` module that `spring-boot-starter-test` does not pull in.
    - 7 tests passing.
- [x] **Step 1 — the API's database role and its own tables** (2026-11-21)
    - **The role plays two parts, and Postgres enforces both.** Against the warehouse it is a
      reader: `SELECT` on `gold` and nothing more, so a stray `UPDATE gold.fact_nsq_sample` from
      the public service fails with "permission denied" instead of silently rewriting published
      CDSCO findings. Against its own tables it is the owner, in a separate `app` schema that
      Flyway migrates and dbt never touches. **Verified on the real database: 17 gold tables
      readable, 0 writable, cannot see `staging` or `ops`.**
    - **Six tests ask the database the forbidden questions** rather than trusting the SQL file:
      write to gold, create a table in gold, read `staging.silver_nsq` (silver *before* its quality
      gate), read `ops.pipeline_run` (the operational run log). They need the real Postgres, so they
      skip when `API_DB_PASSWORD` is absent — the same shape as the Python integration tests.
      Testcontainers cannot answer this: its container has one superuser and none of the grants.
    - **Flyway owns `app`**: numbered SQL, applied once, recorded. Hibernate is set to `validate`
      and never `update` — a schema generated at startup has no history, no review and no rollback.
      A test asserts **nothing was created outside `app`**, because a migration leaking a table into
      `public` is the first step towards two tools editing one schema.
    - **The constraints carry the design, not the Java.** `alert_notifications` has a UNIQUE on
      (watchlist item, alert month), which makes a duplicate email **impossible** rather than
      unlikely: a retry after a half-finished run, two schedulers overlapping, or a redeploy
      mid-send all collide with it. Emails are forced lower-case by a CHECK, or `A@b.com` and
      `a@b.com` become two accounts and the unique index stops meaning anything. A watch term must
      be 3–100 characters, because a one-letter term matches most of the archive and emails the
      user every month, which is indistinguishable from spam. `email_verified` defaults to **false**
      (decision E). Deleting a user cascades, or a deleted account keeps being emailed.
    - **13 schema tests**, each checking a rule the application would otherwise have to remember.
      A constraint enforced only in Java is enforced until the second code path.
    - 🐛 **Spring Boot 4 split auto-configuration into per-technology modules**, and `flyway-core`
      alone gives you a Flyway that sits on the classpath and never runs: no migration, no log
      line, and a bare "relation app.users does not exist" at the first query. It needs
      `spring-boot-flyway` beside it. Same restructuring that caught step 0 with
      `spring-boot-resttestclient`.
    - 🐛 **Testcontainers 2.0 renamed every module** with a `testcontainers-` prefix
      (`postgresql` → `testcontainers-postgresql`), and Spring Boot 4's parent no longer manages
      their versions, so the BOM is imported explicitly.
    - 26 tests passing (6 skipping without the local database, as CI will see them).
- [x] **Step 2 — the public endpoints** (2026-11-21)
      `/api/v1/batches/search`, `/drugs/{id}`, `/drugs/search`, `/manufacturers/{id}`,
      `/alerts/latest`, plus validation and one place where errors become responses.
    - **The batch checker works on the real archive**: searching `TETY01` — punctuation stripped,
      as a user copying from a foil strip would type it — returns **7 findings of `TETY-01`**, each
      with its alert month and a link to the CDSCO document.
    - **Normalisation merges spellings without merging batches.** Letters and digits only,
      upper-cased. Leading zeros are kept (`01` ≠ `001`, both real) and letters are never
      transliterated (`BO1` ≠ `B01`) — those substitutions look helpful and turn one company's
      batch into another's.
    - 🔍 **The rule exists twice, in Java and in SQL**, because the query normalises 7,126 stored
      values and the request normalises one typed value. That is the ONNX problem again, and it is
      guarded the same way: **a test runs both over every batch number CDSCO has published and
      requires identical text**. A disagreement would not error — the user would simply be told
      their medicine is not in the archive.
    - **The sentinel is refused, and the refusal is checked against reality.** `"Not applicable"`
      is the printed batch number on 22 findings; searching for it returns `NOT_SEARCHABLE` with
      an explanation. A separate test asserts the sentinel **is still in the archive**, so the
      refusal cannot quietly become dead code.
    - **A match needs a medicine as well as a batch.** `1`, `6` and `01` are real batch numbers on
      findings from different manufacturers, so a batch-only search would report somebody's
      medicine as flagged on a one-digit coincidence. The 3-character minimum on the medicine name
      is the same idea.
    - **"Close matches" are separate from matches**: the same batch on a *different* medicine is
      returned in its own field, which is how a user discovers they typed the name differently
      from the way CDSCO printed it.
    - **The ethics rules are in the response, not in a page template.** Every result carries the
      disclaimer — including error responses — and "not found" carries the sentence that it is not
      a guarantee of safety, naming the 101-of-111 months the archive covers. A redesign of the
      frontend cannot drop them, and a second client gets them too.
    - **Spurious findings name no manufacturer, structurally.** `Finding`'s constructor *throws*
      if a spurious finding carries one, and the repository nulls it regardless — on top of gold
      having no `manufacturer_id` for those rows at all. **Verified on real data**: batch
      `GTE1350A` appears twice in the archive, once as a genuine finding (manufacturer named) and
      once as spurious (manufacturer null, copied brand in `nameOnPack`), and the API frames each
      correctly.
    - **Fuzzy drug search via `pg_trgm`** (decision B), with the index built by **dbt as a
      post-hook** — dbt drops and recreates every mart monthly, so an index added by hand would
      vanish and nobody would notice until a search got slow. Measured: the index is **11× faster
      when used** (2.4 ms against 27.6 ms), though Postgres still prefers a sequential scan at
      5,651 rows. Both are fast enough today; the index is there for when the archive is not small.
    - **Search says the same medicine can appear twice.** Phase 4 deliberately left the 5,651
      printed names unmerged, so a reader seeing two rows must be told they may be one medicine.
    - **Reads gold with plain SQL, not JPA.** Gold has no entity graph to map, is rebuilt monthly,
      and the API's role cannot write to it — an ORM would add a mapping layer with nothing to map
      and put `save()` within reach of a published CDSCO finding.
    - 🐛 **My own catch-all handler turned every 404 into a 500.** `@ExceptionHandler(Exception)`
      swallows Spring's own status-carrying exceptions, so `/actuator/env` started answering "500,
      quote this reference" instead of 404 — which hides real errors *and* tells anyone probing
      for paths that the one they guessed did something. Caught by the step-0 smoke test, fixed by
      handling `ErrorResponseException` and `NoResourceFoundException` first, with a regression
      test.
    - 🐛 `%` is pg_trgm's similarity operator and needs no escaping in a JdbcClient query; writing
      `%%` produced a SQL grammar error, and the test container also needed the extension created,
      which dbt does in production via an `on-run-start` hook.
    - **Test data is invented** (`db/gold-fixture.sql`) — ADR 0003 keeps real CDSCO rows out of
      git, and a fixture is still git. The names are deliberately fictional. A separate
      `GoldContractTest` asks the **real** warehouse whether every column the API reads still
      exists, so the fixture cannot drift quietly.
    - 88 tests passing (BatchNumber 23, batch search 12, public endpoints 12, HTTP 11, schema 13,
      privileges 6, gold contract 3, architecture 5, smoke 3).
- [x] **Step 3 — accounts, tokens and email verification** (2026-11-22)
      Register, login, refresh, logout, verify. **JWT from Spring Security itself** (`oauth2-jose`
      brings Nimbus), so "Spring Security + JWT" needs no library outside the approved stack and
      nothing is hand-rolled.
    - 🔒 **Registering never reveals whether an address already has an account.** A site about the
      medicines people take is one where "does this person have an account here" is itself
      private, and a public endpoint that answers it is an oracle anybody can query. So
      registration returns **202 with byte-identical text** either way, and when the address is
      taken it emails *that address* a note instead of creating anything. Verified against the
      real stack: two registrations, one account, two emails — both to the owner.
    - **Login fails identically for a wrong password and an unknown address**, and the password is
      hashed even when no user was found. Skipping the hash would make the unknown-address case
      measurably faster, and a stopwatch would then answer the question registration refuses.
    - **Refresh tokens are single-use and rotate**, and **reuse revokes every session that user
      has** — a revoked token presented twice means somebody has a copy, and which holder is the
      real user cannot be known.
    - 🐛 **That protection silently did nothing at first, and a test caught it.** The reuse branch
      revoked every session and then threw — and a thrown exception rolls the transaction back, so
      the revocations were undone and the stolen token kept working. Fixed with
      `noRollbackFor = InvalidCredentialsException`, which is load-bearing rather than tidiness:
      **a security response has to survive the rejection that triggers it.** Confirmed end to end
      on the real stack.
    - **Nothing is stored that can be presented to the API.** Passwords BCrypt (plan §15); refresh
      and verification tokens as SHA-256 of 256 random bits. SHA-256 rather than BCrypt for the
      tokens *because* BCrypt is slow on purpose — that cost is worth paying against a
      human-chosen password and pointless against 256 bits of `SecureRandom`, where it would just
      tax every refresh. Checked in the database: 64-char hashes, `$2a$` password prefix.
    - **Verification links are single-use and expire in 24 hours** — a link that keeps working is
      a credential sitting in an inbox, and inboxes get forwarded, backed up and breached.
      Access tokens live **15 minutes**; they are not checked against a database, so expiry is the
      only limit on a stolen one. The refresh token is the long half, and it *can* be revoked.
    - **The filter chain denies by default.** Public paths are listed; everything else needs a
      token, so an endpoint added later is closed until somebody opens it. Tested: an invented
      token, a token signed with the wrong key, and an anonymous caller are all refused, while a
      real token gets through.
    - 🔍 **Two earlier test expectations were wrong once security existed**, and the code was
      right: an unknown path now answers **401, not 404**, because nothing routes before
      authorisation. That is the better answer — a 404 confirms a path is absent rather than
      present-and-protected, which is exactly what somebody mapping the service wants. The
      catch-all regression test was rewritten to use a path under a *public* prefix, where a 404
      can still be reached.
    - **Time is a `Clock` bean**, so expiry is tested by moving the clock rather than by sleeping
      for thirty days or weakening the assertion to "not null".
    - 🐛 Actuator's **mail health check** broke the context, and turning it off is right in
      production too: it opens an SMTP connection on every poll and a failure flips the service to
      DOWN — so an outage at the mail provider would have Docker restart a working API and take
      the public batch checker down with it.
    - 🐛 A test class that never loaded the gold fixture passed or failed **depending on which
      test ran first** (the container is shared). Fixed by loading it there too, which is the real
      fix rather than reordering.
    - 119 tests passing. Verified end to end against the real stack: register → two identical
      responses → verification email in Mailpit → verify → link rejected on reuse → login →
      refresh rotates → old token revokes everything.
- [x] **Step 4 — the watchlist and its notification emails** (2026-11-22)
      `GET`/`POST`/`DELETE /api/v1/watchlist`, plus a daily job that emails a watcher when a new
      alert month names what they are watching.
    - 🔍 **A new watch must not email the back catalogue, and that needed a migration.** "Watch
      telmisartan" matches findings across most of the archive's 101 published months — so without
      a baseline, adding one watch would have sent about a hundred emails at once, which is
      indistinguishable from spam and would get the sending domain blocked before anybody read
      one. `V2__watchlist_baseline.sql` adds `since_alert_month`, set to the archive's newest month
      when the watch is created. **Verified on the real stack: a new watch recorded `2026-09` and
      sent nothing.** The default is `'9999-12'`, deliberately in the far future, so a row that
      somehow missed its baseline notifies about *nothing* rather than everything — failing closed
      is the right direction for a column that decides whether to email somebody.
    - **A watch is a term, not a product** (decision D), matched on **whole words** against the
      printed product and generic names. Phase 4 left the 5,651 printed names unmerged, so a watch
      pinned to one row would silently miss the same medicine printed another way. Whole words
      because a substring match makes "ace" match "Paracetamol" — tested.
    - **A term can never become a regex.** It is interpolated into a `\y…\y` word-boundary
      pattern, so anything a regex engine would read as syntax is refused at the edge rather than
      escaped later — the same rule ADR 0014's ingredient phrases follow. Tested against `.*`,
      `a|b`, `[abc]`, `^para` and six more.
    - **Nothing is emailed to an unverified address** (decision E), and that is enforced in the
      query rather than in Java, so a bug in the notifier cannot reach an unconfirmed address.
    - **A row is written before the email is sent**, so the UNIQUE constraint on (watch, alert
      month) makes a second send impossible — two overlapping runs, a retry, or a redeploy
      mid-send all collide with the database. The cost is stated rather than hidden: if the row
      commits and the send fails, that one notification is lost rather than retried. For a monthly
      digest, one missed email beats an unbounded number of duplicates.
    - **The API polls; Airflow does not call in.** A webhook between them would need a shared
      secret, a retry policy and a protected endpoint, for a job whose trigger is "is there a month
      we have not told anybody about". A daily query answers that with no new coupling.
    - **Ownership comes from the token, never the request.** There is no user id to tamper with;
      the watch id is scoped by owner, and "not yours" answers 404 because the difference between
      that and "does not exist" is itself information. Tested from both sides.
    - **Every email carries the caveats**: one specific batch, not the medicine or the company; a
      batch absent from an alert is not a guarantee it is safe; the disclaimer; and a link to stop
      watching.
    - **Verified end to end on the real archive**: register → verify → watch "telmisartan"
      (baseline 2026-09, nothing sent) → backdate to 2026-07 → the cron sent **two** emails,
      "6 batches reported in the 2026-09 CDSCO alert" and "8 batches reported in the 2026-08
      alert", with two rows recorded.
    - 🐛 A 50-watch ceiling per account, because every watch is a monthly email and a row in a
      query that runs for every user — and "watch everything" is what the drug pages are for.
    - 🐛 The API answered `"createdAt": null` for a field it advertises: the column is
      database-defaulted and, with `insertable = false`, the saved object never learned the value.
      Now written by the application from the `Clock`, with the column default kept as a backstop.
      Regression test added.
    - 🐛 A step-3 test asserted an authenticated call to `/api/v1/watchlist` returned **404**,
      because the endpoint did not exist yet. Step 4 built it, so the assertion is now the stronger
      one — 200 with an empty list.
    - 159 tests passing.
- [x] **Step 5 — the risk-score proxy** (2026-11-22)
      `GET /api/v1/manufacturers/{id}/risk`. Reads the company's newest row from
      `gold.mart_ml_features` and asks the Phase 8 service to explain it.
    - **Verified end to end on a real company**: score 0.193 for "Aurio Pharma Laboratories
      Private Limited", with Phase 7's approved SHAP wording carried through two services —
      *"Mainly batches reported in the last 24 months (3) raises it… This reflects how often
      batches have been reported, not the quality of the company's medicines."*
    - **The model's own limitations travel to the reader.** Phase 7 attached them to the
      registered model version, Phase 8 serves them from `/explain`, and this endpoint repeats
      them verbatim — including "statistically tied with logistic regression" and the
      under-prediction. Three services, one sentence, no retyping.
    - 🔍 **The model card's biggest caveat is told to the reader it applies to.** A company whose
      history begins after the training cutoff gets *"the model is considerably less accurate for
      such companies"*; one the model trained on is told it is in the group it predicts best. 48%
      of the test window was in the weaker group (PR-AUC 0.269 against 0.438), and averaging over
      that difference would have hidden it from exactly the people it affects.
    - **A score of null, never zero.** When the service cannot answer, `available` is false and
      `score` is null — a zero would read as "this company is safe", which is the opposite of "we
      do not know". Same for a company with no findings at all: *"no reported findings… that is
      not a statement about its medicines."*
    - **The page survives the model being down**, measured: with `risk-api` stopped the endpoint
      answered in **165 ms** with `available: false`, and the manufacturer page itself still
      returned 200. Timeouts are 1 s to connect and 2 s to read, against an endpoint whose
      measured p95 is 10 ms.
    - **A null feature stays null.** `getDouble` reads a SQL NULL as 0.0, so the proxy checks
      `wasNull()`: a share is null when the window held no findings to divide, and Phase 7 trained
      the model to read that difference. The explanation renders it as "(unknown)".
    - 🐛 **The worst bug of the phase, and the fallback hid it perfectly.** Java's `HttpClient`
      defaults to offering an HTTP/2 upgrade — `Connection: Upgrade`, `Upgrade: h2c`, body in
      chunked transfer encoding — and **uvicorn answers that with 422 "body: Field required"**:
      the headers arrive, the body does not. The client turned the 422 into "no score today",
      which is *identical* to the service being down, so in production this would have been a
      permanently missing score with nothing logged as an error. Found by capturing the raw
      request with `nc` after ruling out the content type, the request factory, a string body and
      IPv6 in turn. Fixed by pinning HTTP/1.1, with a regression test that fails loudly if the pin
      is removed.
    - The live tests are what caught it. They run against the real Phase 8 container and skip
      without it, so CI stays green while this machine checks the thing CI cannot.
    - 171 tests passing.
- [x] **Step 6 — Redis caching and rate limiting** (2026-11-22)
    - 🔍 **Cache keys carry the warehouse's alert month**, so the monthly pipeline run invalidates
      every entry by producing a newer month. Nothing has to remember to flush anything, and the
      failure mode that actually matters — the site serving last month's answers while claiming to
      be current — cannot happen. Verified on the real stack: the key is
      `drugSearches::2026-09:search:[telmisartan, 20]`, and **192 ms cold became 17 ms cached**.
      The alternative, a flush endpoint Airflow calls after each run, is one more moving part whose
      silent failure is exactly that worst case.
    - 🐛 **The cache would have broken every endpoint on its second call, and my first two tests
      missed it.** A generic JSON serializer writes an object without its type and hands back a
      `LinkedHashMap`, so the second request to a cached endpoint fails with `ClassCastException`.
      Both passing tests only checked that a *key existed*; the one that read a value back is what
      found it. Each cache now declares the single type it holds. The other fix — Jackson's default
      typing — writes class names into Redis and makes deserialisation polymorphic, a well-known
      attack surface, for a cache where every entry has exactly one possible type anyway.
    - **`disableCreateOnMissingCache`**: a cache name that is not declared fails rather than
      quietly getting a generic serializer, which is how the bug above would come back.
    - **Nulls are never cached.** A miss stored as a hit means a medicine added next month keeps
      answering "no such medicine" until the TTL expires.
    - **The rate limiter is ~30 lines of Redis `INCR` + `EXPIRE`** (decision C, no Bucket4j). Only
      the first request in a window sets the expiry, so the window starts at the first request
      rather than sliding forward forever — tested with a real TTL, which an in-memory map could
      not have checked. Verified on the real stack: counts down, 429 at the limit, and
      `Retry-After: 53` rather than "try again later".
    - ⚠️ **It fails open**, deliberately: the limiter sits in front of the batch checker, which is
      why the site exists. Failing closed would let a Redis blip take down the public service —
      trading a real outage for a hypothetical abuser. The warning is logged so the outage is
      visible.
    - 🔒 **The caller is the socket address, not `X-Forwarded-For`.** That header is trivially
      forged, so trusting it here would hand every caller a fresh identity per request — a limit an
      attacker opts out of is worse than none, because it looks like protection. Phase 12 adds the
      reverse proxy, and `server.forward-headers-strategy` belongs there, at a boundary that can
      actually be trusted.
    - **Login and the watchlist are deliberately not limited by IP**, and a test says so: a shared
      office or college address would otherwise lock everybody out of their accounts after a few
      attempts. Brute-force protection belongs per-account. `/actuator/health` is exempt too, or
      the service would fail its own monitoring.
    - 🐛 Boot 4 ships **Jackson 3** (`tools.jackson`), so `GenericJackson2JsonRedisSerializer`
      compiles and then dies at startup with `NoClassDefFoundError` on a Jackson 2 class. The
      Jackson 3 equivalents drop the version from the name.
    - 🐛 A 5-per-minute test limit spent the budget for **the whole suite** — all the HTTP tests
      share one Redis — so three unrelated tests started failing with 429. The limit is now high by
      default and lowered only in the class where it is the subject.
    - 187 tests passing.
- [x] **Step 7 — the Superset guest-token endpoint** (2026-11-22)
      `POST /api/v1/dashboards/{key}/guest-token`, public and rate-limited, plus
      `GET /api/v1/dashboards` listing what may be embedded.
    - **Verified end to end against the real Superset**, token decoded rather than taken on trust:
      `type: guest`, exactly one resource (`09493340-…` for `states`), and
      `user: {username: guest}` — so Superset resolves it to the read-only role rather than to the
      service account's.
    - 🔒 **The service account holds exactly one permission.** Confirmed in Superset's own tables:
      `embed_service` → role `GuestTokenIssuer` → **1 permission**,
      `can_grant_guest_token on SecurityRestApi`. It cannot read a dashboard, run a query or see a
      dataset, so a leak of that password buys the ability to mint tokens for dashboards that are
      already public — and nothing else. Phase 6 refused `can_grant_guest_token` to anonymous
      visitors and left a note that Phase 9 would do this server-side; this is that.
    - 🔍 **The `EmbeddedViewer` role is built by copying the Public role's permissions**, not by
      restating them. An embedded dashboard should do exactly what an anonymous visitor can, and
      copying keeps that true when Phase 12 tightens Public — rather than two lists drifting apart,
      one of which somebody forgets. It is still a *separate* role, so the two remain separate
      decisions.
    - **The allowlist is a map from a public key to Superset's UUID**, so a caller cannot ask for a
      dashboard nobody listed — one added later is private until somebody lists it. Verified: an
      unlisted key is 404. And `GET /api/v1/dashboards` publishes **keys only**; a published UUID
      would let anybody holding a stolen service password skip the discovery step.
    - 🐛 **An unconfigured dashboard was in the allowlist with an empty UUID.** `application.yaml`
      declares all four keys with empty defaults so the shape is visible, and without filtering,
      an unset one was published as embeddable and would have minted a token for the UUID `""` —
      failing in a way that looks like an outage. A test caught it; blank values are now dropped.
    - 🐛 **The catch-all handler was still swallowing statuses, and this time I fixed the family
      rather than the instance.** A GET to the POST-only token endpoint answered "500, quote this
      reference" instead of 405. Spring's status-carrying exceptions do not share a base class —
      `ErrorResponseException` is one, but a wrong method only implements `ErrorResponse` — so
      step 2's fix for 404 did not cover it. The handler now asks for the **interface**, which
      covers the whole family instead of being whack-a-mole.
    - **POST, not GET**, because it mints a credential: a GET would be cached by a browser, a proxy
      or a CDN, and a cached bearer token is a token handed to whoever asks next. Tested.
    - **Five-minute tokens, signed with their own secret.** Superset falls back to `SECRET_KEY`
      when `GUEST_TOKEN_JWT_SECRET` is unset, which would mean one leaked value forged both session
      cookies and guest tokens.
    - 🐛 **Two Superset specifics found by running it.** The permission is on `SecurityRestApi`, not
      `Superset` — the script stopped with "does not exist in this build" rather than silently
      granting nothing, the same habit as Phase 6's invented `can_read on ChartDataRestApi`. And
      the guest-token POST needs the **full CSRF handshake**: bearer token, CSRF token, *and* the
      session cookie issued with it. Phase 6's `superset_api.py` docstring had predicted exactly
      this: "the same one Phase 9's guest-token endpoint will have to do".
    - **The endpoint is rate-limited**, named specifically by plan §9 step 10: it mints a credential
      and makes an outbound call per request, so it is the easiest endpoint here to turn into a
      denial of service against a third service.
    - 🐛 Two tests asserted on counts that depended on the machine — the number of configured
      dashboards, and the number of Redis keys other classes had flushed. Both now assert the
      property instead, which is the better assertion anyway.
    - 200 tests passing.
- [x] **Step 8 — CI, Swagger, the done-when demonstration** (2026-11-22)
    - **springdoc-openapi 3.2.1**, the first release built against our exact Spring Boot parent
      (4.2.0) rather than 4.1.x — chosen by checking its own POM, not assumed. Publishes
      `/v3/api-docs` (OpenAPI 3.1) and a Swagger UI at `/swagger-ui.html`, generated from the
      controllers themselves so the document can't drift from what the API does. Already listed
      in the locked stack (plan §6), so no ADR — this is implementing it, not adding a tool.
    - `OpenApiConfig` writes the one thing springdoc can't infer: *why*. The `info.description`
      quotes `PublicNotes` verbatim — the same disclaimer, "not found" caveat and spurious-pack
      explanation the JSON responses carry — so CLAUDE.md §6's wording reaches whoever finds the
      API before the website, from one source rather than a second copy that drifts.
    - Every one of the 15 operations across all 8 controllers got an `@Operation` summary and
      `@Tag`; the watchlist controller additionally carries `@SecurityRequirement("bearer-token")`.
      `/v3/api-docs` and `/swagger-ui.html` opened in `SecurityConfig` — public, because the API
      underneath is: a description of already-open endpoints leaks nothing.
    - 🔍 **No global security requirement.** A bearer scheme is declared in `components` but never
      applied document-wide — only per-operation on the watchlist. A global requirement would
      label the batch checker as needing an account, which is backwards for a public-interest
      site whose whole point is working for a logged-out visitor.
    - **`OpenApiTest`** (10 tests, `RestTestClient` against the real `/v3/api-docs`) is the test
      with teeth here: it asserts every published operation has a summary *and* a tag, so adding
      an endpoint without documenting it fails the build instead of quietly shipping a less-true
      page — the same "rot silently" failure mode step 7 already fixed twice elsewhere. Also
      checks: OpenAPI 3.1, the plan's 15 paths all present, the disclaimer text present, the
      batch-search minimum-length validation rule surfaced in the schema, `/actuator/health`
      *not* published as API, and the Swagger page reachable with no token.
    - CI already runs `./mvnw -B verify` as its own `backend` job (added step 0) — step 8 is
      confirming that job now also runs `OpenApiTest`, not adding a workflow.
    - **Phase 9 done-when, demonstrated live** against the real stack (Postgres, Redis, Mailpit,
      the risk service, Superset — all already running, nothing started just for this):
      - All endpoints answer: `batches/search` → `NOT_FOUND` with the full disclaimer,
        `alerts/latest` → 200, `drugs/search` → 200.
      - `POST /api/v1/dashboards/states/guest-token` → a real Superset JWT, decoded:
        `type: guest`, one resource (the `states` dashboard's UUID), `exp` 300s out.
      - `POST /api/v1/auth/register` → the verification email landed in Mailpit, subject
        "Confirm your email address", addressed to the registered account — the same pipeline
        the watchlist's own notification email rides on, already proven end-to-end in step 4.
      - `GET /v3/api-docs` → 200, `title: DrugWatch India API`, 15 paths. `/swagger-ui.html` →
        302 → 200 (serves the page).
      - Full suite: **210 tests passing**, `spotless:check` clean, `mvn verify` green.
    - **Phase 9 is done.** All eight steps complete; the done-when criteria are demonstrated above,
      not just asserted.

**Done when:** all endpoints work, the guest-token endpoint returns a valid Superset token,
watchlist emails arrive in Mailpit, the test suite passes in CI, Swagger docs are live. ✅

✅ **Phase 9 signed off by Harith, 2026-11-22.**

---

## Phase 10 — LLM Extraction

Approved 2026-11-22. Plan: `DRUGWATCH_PHASES.md` §9 Phase 10, §13 (LLM design).
Goal: a fine-tuned LLM fallback for the rows the rule-based parser can't handle correctly, used
only where the parser itself is unsure.

**Finding that reshapes the phase, before any code:** Phase 2's own extraction report had already
measured this, and I re-checked it against live bronze (2026-11-22, read-only count): of the
archive's 103 low-confidence records, only **3 are parser mistakes** — the other 100 are low
because the *PDF itself* prints `NIL`, a placeholder or an Excel day number, which the parser
copies correctly. In the 9-test-split PDFs' low-confidence rows specifically, only **1** (row 149,
a two-part pack) is a parser error. So the plan's done-when — beat the baseline on low-confidence
test rows — comes down to one row, and the harder, more realistic risk is the opposite failure:
an LLM turning a genuine `NIL` into a plausible-looking invented date, which CLAUDE.md §5
explicitly forbids ("impossible dates or invented fields are rejected").

**Four decisions taken at the start** (Harith, 2026-11-22 — "go," taking all recommendations):
- **D1. Train locally, on the Mac, not Colab.** The model has to run monthly in the pipeline and
  later on a cheap production CPU, so it is capped at ~0.5–1B parameters regardless of where it's
  trained — Colab's extra GPU headroom buys nothing here. Training locally keeps the fine-tune a
  `uv run` command in the repo and keeps the labels (git-ignored, ADR 0003) off a third-party
  service. Cost: Docker (4.8 GB of the Mac's 8 GB, MLflow alone at ~1.9 GB) gets stopped during
  training runs — measured 1.3 GB free on the Mac side with everything up.
- **D2. Output schema deviates from plan §13: values exactly as printed; `generic_name` dropped.**
  **ADR 0019.** Asking for `YYYY-MM` invites the model to normalise (invent) a date; asking for
  what the cell prints lets the same date parsers that already handle the rule parser's output
  (Phase 3, proven on 5 formats) handle the LLM's too. `generic_name` has no label and no parser
  field to score it against.
- **D3. Two gates, not one.** Gate 1 is the plan's own criterion (beat the baseline on the 9
  low-confidence test rows), reported honestly including that n=9 and one row decides it — the
  Phase 7 precedent for a result that may not be a clean win. Gate 2 is new: across the *whole*
  69-row test split, F1 must not fall below the parser's 99.5%, and **zero invented values** may
  be accepted. Gate 2 is the one that actually protects the data.
- **D4. The fallback may only change a field that the parser flagged low-confidence, and only if
  the LLM's value passes three checks: schema (exactly the 6 fields), grounding (the value appears
  in the row's own source text — it cannot be invented), and plausibility (any date it gives must
  be a possible date).** Everywhere else, the parser's value is kept even if the LLM disagrees.

**Also approved:** a reported (non-gating) held-out-layout experiment — train with one whole
layout family excluded, test on it — because that is the realistic case where an LLM earns its
place: a new CDSCO layout the rule parser returns nothing for.

**Candidate models to try zero-shot in step 2** (Apache-2.0, confirmed via each model's Hugging
Face page before writing it down, not assumed from the name):
- `Qwen/Qwen2.5-0.5B-Instruct` — Apache-2.0, confirmed.
- others to be checked the same way when step 2 runs.

- [x] **Step 0 — `llm/` project foundations** (2026-11-22)
    - New `llm/` uv project: torch 2.15, transformers 5.24, peft 0.22, accelerate 1.16, confirmed
      against PyPI (not assumed) and with a real macOS/cp313/arm64 wheel for torch.
    - `smoke_test.py` proves four things end to end: PyTorch sees Apple Silicon's GPU (MPS); the
      first candidate model, `Qwen/Qwen2.5-0.5B-Instruct` (Apache-2.0, confirmed on its own model
      page), downloads, loads and generates; PEFT wraps it with a LoRA adapter touching only
      0.11% of its 494M parameters; and the memory cost is this process' own peak RSS, not a
      guess from how much the Mac appears to have free.
    - 🐛 **My first memory reading was off by 1024×** (reported "1,045,088 MB"). `ru_maxrss`'s
      unit depends on the OS (bytes on macOS, KiB on Linux) and my first version guessed the unit
      from the value's size instead of asking `platform.system()` — the same bug shape as Phase
      2's Excel-day-number dates: a number in the wrong unit still looks like a plausible number.
    - 🔍 **"Docker has to be stopped to train" (my own D1 framing) turned out not to be true at
      this stage, and the reason matters.** `docker compose stop` left Docker Desktop's VM
      resident — `docker info` still reported it holding 4.8 GB regardless of which containers
      were running, so only quitting the whole app released anything. But the real test — running
      the smoke test with the full stack up — passed fine: **375 MB peak RSS** with a warm model
      cache, vs 1.4 GB on the earlier cold-cache run with Docker quit (that gap was the Hugging
      Face download, not Docker's absence). A 494M-parameter model's load and one generation fits
      comfortably either way. Whether a LoRA *training* run (gradients + an optimizer's state,
      not just a forward pass) needs Docker stopped is still open — measured for real at step 4,
      not assumed now.
    - `docs/adr/0019-llm-output-schema-and-training-location.md` records the output-schema
      deviation from plan §13 (values as printed, `generic_name` dropped) and the local-training
      decision (D1/D2).
- [x] **Step 1 — training data** (2026-11-22)
    - **737 examples** written to `data/llm-training/train.jsonl` (git-ignored, real CDSCO text:
      ADR 0003) — 175 from the labelled eval set's train rows, 562 from high-confidence parser
      output, both from train-split PDFs only, family E excluded. 33 rows skipped: unlabelled and
      not high-confidence, or a label with an unreadable ("/u") field.
    - **INPUT has no column assignment on purpose.** `row_text()` reuses `second_reader.row_strips`
      (Phase 2, already built and tested to crop the label pictures) to find the header strip and
      the row's own strip(s), then dumps every word pdfplumber finds inside them in reading order
      (top to bottom, then left to right) — the same jumbled-across-columns text a rule parser
      would see before its own column-alignment step runs. Teaching the model on pre-aligned cells
      would train it on the one thing it doesn't need to learn.
    - 🔍 **`second_reader.row_strips()` already solved the hard part of this step**, built for a
      different reason (cropping label pictures) months earlier. No change to any Phase 2 file was
      needed — confirmed first by checking every call site of `ExtractedRow` (one, in
      `table_parser.py`) before considering touching it, and finding the bbox data was already
      computed and already exposed.
    - **OUTPUT is a label where one exists, else the parser's value only where the parser itself
      was high-confidence** (`target_fields`). An unlabelled low-confidence row is left out
      entirely: training the model on the parser's own uncertain guess there would risk teaching
      it exactly the mistake this phase exists to catch.
    - **Leakage checked twice**: inside `training_data.py` itself (refuses to write a file
      containing a family-E example) and in a test that reads the real written file back and
      confirms every source PDF is train-split and no family-E row is present. Both pass.
    - **Found and declined to chase: 3 more low-confidence test-split rows exist beyond the
      sampled 69** (`state-nsq/2024-06/11467` p1 S.No 5; `state-nsq/2025-06/12926` p6 S.No 59 and
      p10 S.No 100) — my own Phase 10 plan had proposed labelling these to thicken Gate 1's thin
      n=9. Checked their confidence reasons first: all 3 are `missing`/`not stated` — the
      PDF-prints-nothing category that Phase 2 found accounts for ~97% of low-confidence rows
      archive-wide, not the `parser warning` category a real parser mistake would show up as.
      Also: appending them to `eval/manifest.csv` would break two of Phase 2's own signed-off
      regression tests, which hard-assert 309 rows. Recommending Harith skip labelling these three
      — Gate 1 stays at its honest n=6 (test-split, labelled, low-confidence rows already in the
      manifest) rather than growing by rows unlikely to carry a parser mistake, at the cost of
      reopening a frozen, tested artifact.
    - 11 tests passing (7 on `target_fields`'s decision logic, 1 constant, 1 memory-unit, 2 from
      step 0; plus the real-file leakage test, which ran against the actual 737-row output above).
- [x] **Step 2 — choose the model** (2026-11-22)
    - **53 validation examples** built (`validation_data.py`) — every validation-split row that
      has a readable label, scored against the label only (never the parser's own output: scoring
      a model against the parser would be circular, a model that copies the parser's mistakes
      would look perfect). Family E never appears in validation/test at all, so there was nothing
      to additionally exclude here, unlike step 1's train set.
    - **Zero-shot comparison, 3 Apache-2.0 candidates** (`zero_shot.py`, scoring reused directly
      from Phase 2's own `evaluate.Counts`/`outcome` — one comparison method for the parser and
      every LLM candidate):

      | Model | JSON valid | Right schema | Grounded | Overall field F1 | Time/row |
      |---|---|---|---|---|---|
      | Qwen2.5-0.5B-Instruct | 100% | 98.1% | 97.2% | 19.7% | 1.20s |
      | **Qwen2.5-1.5B-Instruct** | 100% | 100% | 93.7% | **41.1%** | 4.42s |
      | SmolLM2-360M-Instruct | 49.1% | 7.5% | 91.7% | 2.3% | 2.42s |

    - **SmolLM2-360M eliminated outright**: half the time it can't even produce parseable JSON.
      Not a contest between it and the Qwen models - it simply cannot follow the task's format.
    - 🔍 **`manufacturer` and `product_name` score near 0% F1 on every single candidate**, despite
      grounding staying above 90% throughout. Not the models inventing values - the strict
      whitespace-collapsed exact-match scoring (the same rule the rule parser is held to) gives
      zero credit for a long, multi-line address or bracketed product name that's almost right
      but not byte-identical. A parser that copies a cell verbatim either matches or doesn't; a
      generative model producing a slightly different line-wrap gets nothing for being close.
      Reported as a metric-harshness finding to carry into step 4/5, not swept under the rug.
    - 🐛 **The first full run stalled for 30+ minutes and had to be killed.** All three models were
      loaded in **float32** (the 1.5B candidate alone needs ~6 GB of weights at 4 bytes/param) with
      nothing freed between runs, on a Mac where Docker Desktop's VM was separately holding ~4.8 GB
      — total demand far past 8 GB, and the process sat in an uninterruptible-sleep state burning
      almost no CPU for 30 real minutes while it thrashed. Fixed three ways: **bf16** instead of
      float32 (halves memory, inference-only so it costs nothing this phase trains against),
      explicit `del model; gc.collect(); torch.mps.empty_cache()` between candidates (MPS caches
      allocations even after Python frees the tensors), and Docker Desktop fully quit for the
      run - this is the real answer to step 0's open question about whether heavy LLM work needs
      Docker stopped: a single forward pass didn't; three sequential models generating 53 rows
      each in float32 did.
    - 🐛 **My own stall-visibility fix was itself invisible to the monitoring it was built for.**
      Added a per-row progress print using `end="\r"` (a nice overwriting counter at a live
      terminal) - but a line with no trailing newline is invisible to `tail -f | grep`, which is
      exactly how a backgrounded run gets watched. Changed to a real newline every 5th row.
    - **Decision (Harith, choosing between keeping the 0.5-1B cap, lifting it, or fine-tuning both
      sizes before deciding): lift the cap to Qwen2.5-1.5B-Instruct.** ADR 0019 amended: the cap's
      original reasoning assumed a bulk workload, but the fallback only ever runs on ~103
      low-confidence rows archive-wide - a handful a month, not every row - so 4.42s/row is cheap
      in absolute terms even on a modest CPU server. Step 4 fine-tunes 1.5B only.
    - 22 new tests passing (11 on `prompting.py`'s parsing/grounding logic, including a test that
      initially failed because of MY OWN wrong expectation, not the code - `grounded()` correctly
      doesn't treat a hyphen as whitespace; fixed the test, not the function).
- [x] **Step 3 — the validator** (2026-11-22)
    - `validator.py`: three checks matching decision D4. **Schema** (exactly the right fields,
      already built in step 2's `parse_reply`), **grounding** (a value must appear in the row's
      own source text, `prompting.grounded`), **plausibility** (`plausible`, reusing
      `confidence.field_problem` - the *same* shape check Phase 2 already runs on the rule
      parser's own output, so the LLM is held to an identical bar, not a looser one). A genuinely
      blank value is treated as plausible on purpose: an empty cell is a real, checkable answer,
      not a hallucination, and rejecting all blanks would make the model unable to ever correctly
      report one.
    - `merge()` is D4 itself: the fallback may replace a field **only if the parser flagged it
      low-confidence**, and only with a value that passes every check. Every other field keeps
      the parser's value even when the LLM disagrees - a missed correction is accepted, a wrong
      one is not.
    - **The adversarial test the plan asked for by name passes**:
      `test_nil_can_never_become_a_fabricated_date` - a source cell printing `NIL`, with the LLM
      inventing a plausible-looking `09/2024` that never appears anywhere in the row's text, is
      rejected on grounding alone, however well-formed the date looks. CLAUDE.md §5's "impossible
      dates or invented fields are rejected" has a specific test asserting exactly that now,
      instead of being a sentence nothing checks.
    - Other adversarial cases covered: an extra invented field (e.g. a smuggled-in
      `generic_name`) fails the whole reply, not just that one field; a grounded but malformed
      batch number (copied words with no digit) is rejected on plausibility even though it's real
      text from the row; a well-formed-looking but never-printed date is rejected on grounding
      even though it parses as a valid date shape.
    - 10 new tests, 33 passing overall in `llm/`.
- [~] **Step 4 — LoRA fine-tune, tracked in MLflow** (in progress, 2026-11-23: pipeline built and
  proven at small scale; the real run needs Harith's hands in Colab, then `publish_run.py`)
    - `dataset.py`: loss-masked tokenization — the model is trained only to predict the JSON
      answer, with every prompt token labelled -100. 10 tests (4 need the real tokenizer,
      network-only, no weights).
    - `train.py`: a LoRA fine-tune of Qwen2.5-1.5B-Instruct (step 2's choice). Attention-only
      LoRA (`q_proj,k_proj,v_proj,o_proj`, r=8) to keep the optimizer's own memory small.
    - 🐛 **My first diagnosis was wrong, and I'm recording the correction rather than quietly
      fixing it.** The first full smoke test (10 rows) took 25m57s on `transformers.Trainer`,
      which I diagnosed as Trainer-specific MPS overhead and "fixed" by hand-writing a plain
      training loop instead. The plain loop was JUST AS SLOW (111s/example) on the real data —
      Trainer was never the cause. The real cause, found by timing forward+backward at
      increasing sequence lengths directly: a **cliff**, not a curve, in PyTorch's MPS backward
      pass — 200 tokens took 2.5s, 400 tokens took 135s (53x for 2x the length; normal O(n²)
      attention scaling predicts ~4x). `attn_implementation="eager"` softens it (43.7s at 400
      tokens) but the cliff is still there. Real training rows average 360-505 tokens — squarely
      past it. At the measured rate the full run (737 rows x 3 epochs) would have taken ~60
      hours. (A repo-wide lesson worth naming: I jumped from "found *a* plausible cause" to
      "fixed it" without re-measuring against the real failure case first. The thing that
      actually settled it was timing the SAME operation at increasing sequence lengths in
      isolation, not reasoning about what Trainer might be doing differently.)
    - **Decision (Harith, choosing between chasing more MPS-specific fixes, shrinking every
      sequence to fit under the cliff, or moving training elsewhere): train on Google Colab's
      free GPU.** `docs/adr/0019-...md` amended a second time — this reverses the ADR's original
      "trains on this Mac" half, keeping everything else (schema, prompt, LoRA config,
      production target) unchanged. `llm/notebooks/colab_train.ipynb` inlines copies of
      `prompting.py`'s and `dataset.py`'s logic (a one-off training environment, not worth
      installing the monorepo's cross-package plumbing into) and runs the real 737-example,
      3-epoch job on a T4.
    - **The data trade-off is named, not glossed over**: `train.jsonl` holds real CDSCO text,
      kept off git per ADR 0003; using it in Colab means a private, personal upload — not
      publishing it (ADR 0003's actual concern is the public live site), but a real exception to
      "stays on the Mac," recorded as such. Deleted with the Colab runtime; only the adapter (a
      few MB of LoRA weights, no row text) comes back.
    - **`tracking.py` + `publish_run.py`**: the lightweight half of this step, deliberately
      separate from `train.py`. A training run needs the memory a model plus gradients plus an
      optimizer's state takes, competing with Docker's resident VM for the same 8 GB (as amended
      above); `publish_run.py` loads no model at all, so it is the one allowed to need Docker up
      — logs params/metrics to MLflow and uploads the adapter as an artifact, reading only
      `run_info.json` and the small `adapter/` directory a finished run leaves behind.
    - 7 new tests (`load_run`'s file-existence errors; `train()`'s own step-counting /
      grad-accumulation math with a fake model, no GPU needed) plus the tokenization tests above.
      42 fast tests passing in `llm/`.
    - 🐛 **Found by Harith's first real run, not by me**: the notebook's `%pip install` cell
      force-reinstalled `torch==2.15.0` over Colab's own preinstalled, GPU-matched build. Colab
      crashes and silently restarts its kernel when that happens - which wiped every earlier
      cell's state, including `import torch`, surfacing many cells later as a confusing
      `NameError: name 'torch' is not defined` right as the LoRA/model cell started (nowhere near
      the actual cause). Fixed two ways: the install cell no longer touches `torch` at all
      (Colab's own build is already CUDA-matched - reinstalling it was never necessary), and every
      cell that uses `torch` now imports it locally, so the notebook survives a kernel restart
      from any cause (this one, or Colab's own idle-disconnect) without a misleading error miles
      from its real source.
    - 🐛 **The first real end-to-end run completed training (loss 0.57 → 0.027 over 1,668
      micro-batches, ~39 minutes on a T4) and then lost its own result.** A single browser
      download (`files.download()`) was the only path for the trained adapter to leave Colab's
      ephemeral `/content/` storage, and it had no backup: the runtime disconnected (free-tier
      GPU quota, likely exhausted by the run that had just finished) before the download
      actually completed, and `/content/` - adapter included - died with the session. Also
      found: **181 of 737 examples (24.6%) were dropped** for exceeding `MAX_LENGTH=512` tokens -
      worth revisiting if step 5 shows `manufacturer` is still weak, since long addresses are the
      likely rows being dropped.
    - **Fixed the actual design flaw, not just retried:** the save cell now mounts the
      notebook-runner's own Google Drive and copies the raw adapter files there FIRST - a step
      that succeeds or fails on the spot, with nothing async or browser-dependent to silently
      lose later - and only THEN attempts a convenience browser download, catching and reporting
      any failure there without losing the Drive copy. A single fragile step with no backup is
      exactly the kind of thing worth fixing generally, not just rerunning past.
    - **Still to do:** Harith re-runs the Colab notebook (now saving to Drive first); the adapter
      comes back and gets published via `publish_run.py`; step 4 closes once that run is logged
      in MLflow.
- [ ] Step 5 — single-use test evaluation (both gates, `docs/llm-extraction-report.md`)
- [ ] Step 6 — pipeline integration (fallback, `extraction_method = llm`, Airflow task, GE check)
- [ ] Step 7 — CI (model-dependent tests skip without a model) and the done-when demo

**Done when:** the LLM beats the rule-based baseline on labelled-eval-set F1 for low-confidence
rows (plan's gate), **and** it never lowers whole-test-split F1 below the parser's baseline or
accepts an invented value (this phase's added gate).

---

Checklists for later phases are copied in from `DRUGWATCH_PHASES.md` §9 when each phase starts.

---

## Decision log

| Date | Decision | Record |
|---|---|---|
| 2026-11-03 | Superset embedded SDK in Next.js (Phase 11); Spring Boot guest-token endpoint (Phase 9) | ADR 0001 |
| 2026-11-03 | `spring-boot-starter-mail`; Mailpit in local dev (Phase 0); Brevo SMTP in production; Airflow alerts use the same SMTP | ADR 0001 |
| 2026-11-03 | onnxmltools approved for Phase 8 | ADR 0001 |
| 2026-11-03 | Keep Spark; add a Pandas vs PySpark benchmark to Phase 3 (`docs/benchmarks.md`) | ADR 0001 |
| 2026-11-03 | Gold layer = dbt marts in Postgres (raw → bronze → silver → gold) | ADR 0001 |
| 2026-11-03 | Project lives in `~/drugwatch-india`, separate from OpsPilot | — |
| 2026-11-03 | Gold layer confirmed = star schema + `mart_*` tables | ADR 0001 |
| 2026-11-03 | "Gold set" renamed to "labelled eval set" | Plan §9, §13, §24 |
| 2026-11-03 | Teaching mode added to `CLAUDE.md` §2 | CLAUDE.md |
| 2026-11-03 | RustFS replaces MinIO (MinIO community edition discontinued) | ADR 0002 |
| 2026-11-03 | Dev host ports: Postgres 5433, Redis 6380 (OpsPilot uses 5432 and 6379) | `docker-compose.yml` |
| 2026-11-03 | GitHub repo is public: HARITH935/drugwatch-india | — |
| 2026-11-03 | Language linters added when each language appears (Python: Phase 1, Java: 9, TS: 11); tool choice needs approval then | `lint.yml` |
| 2026-11-04 | Buckets created by a one-shot `rustfs-init` job (compose profile `setup`) using curl's SigV4 signing: no new tool | `docker-compose.yml` |
| 2026-11-04 | Local RustFS access key rotated after it was accidentally shown in terminal output; old key verified dead (403) | — |
| 2026-11-04 | CDSCO NSQ portal (cdscoonline.gov.in JSON, 2019 →) is the primary source; PDFs kept for 2017–2018 and Phase 2 | ADR 0004 |
| 2026-11-04 | Anonymous-visitor access rule; manual browser download where blocked (NPPA IPDMS); Pharma Sahi Daam not used | ADR 0003 |
| 2026-11-04 | CDSCO and Jan Aushadhi data not published until permission recorded; requests drafted | ADR 0003, `docs/permissions.md` |
| 2026-11-04 | Python tooling: requests, boto3, uv (one project per Python folder), pytest, ruff (repo-root config); Python 3.13 | ADR 0005 |
| 2026-11-04 | Retries hand-written so every attempt passes the 3 s/host limiter (urllib3 `Retry` retries instantly once) | ADR 0005 (amended) |
| 2026-11-04 | raw/ layout: content-addressed `<prefix>/<sha256>.<ext>` + `.meta.json` sidecar written last ("done" marker) | `docs/data-sources.md` §6 |
| 2026-11-05 | Rate limit measured from the END of one request to the START of the next (slow responses can't shorten the gap). The limiter is per process: run each host's downloads in one process/Airflow task | `fetcher.py` |
| 2026-11-05 | CDSCO portal raw prefix `cdsco-portal/<nsq\|spurious>/<YYYY-MM>`; stored months skipped unless `--refresh` (recent months change as states report late) | `docs/data-sources.md` §6 |
| 2026-11-05 | CDSCO alerts HTML parsed with Python's built-in `html.parser` (one simple table), so no new library (BeautifulSoup would need approval) | `sources/cdsco_pdf.py` |
| 2026-11-05 | CDSCO PDF raw prefix includes CDSCO's file id (`cdsco-pdf/<kind>/<YYYY-MM>/<file id>`) so two documents for one month never collide; titles whose month doesn't fit the release date are skipped and reported, not stored | `docs/data-sources.md` §6 |
| 2026-11-05 | Jan Aushadhi stored as one snapshot per collection month (`jan-aushadhi/products/<YYYY-MM>`); guest token validated as a JWT before use and never stored or logged | `sources/jan_aushadhi.py` |
| 2026-11-05 | Lint false positives are silenced per line with a reason (`# noqa: S105 (...)`), never by disabling a rule | `ruff.toml` |
| 2026-11-05 | Manual drops stored under `<source>/<dataset>/<period>`; download time defaults to the file's modified time and the sidecar says which was used | `manual_drop.py` |
| 2026-11-05 | nppa.gov.in's missing intermediate (Sectigo DV R36) supplied in `certs/` after verifying it against certifi; verification never turned off; certificate errors never retried | ADR 0006 |
| 2026-11-05 | NPPA pages whose table is the data (2014 DPCO lists) stored as `.html` exactly as received (CSRF token and visitor counter included: raw is never edited) | `sources/nppa.py` |
| 2026-11-05 | Unlisted Aug–Dec 2024 CDSCO PDFs skipped: portal JSON covers those months; no URL guessing | `docs/data-sources.md` §5 Q3 |
| 2026-11-07 | Inventory check re-hashes every raw/ file and exits 1 on any problem, so the Phase 5 pipeline can fail on it | `inventory.py` |
| 2026-11-07 | Step 6: CDSCO PDFs all text (no OCR); pre-2024 central PDFs vaccine-only; Phase 2 focus = Apr 2024 – Jun 2025 layout families B and C, benchmarked against the portal | `docs/data-sources.md` §7, ADR 0004 update |
| 2026-11-07 | Local Docker VM clock can drift after Mac sleep (`RequestTimeTooSkewed`): restart Docker Desktop; long jobs run under `caffeinate -i` | CLAUDE.md §10 |
| 2026-11-08 | Phase 2 approved | — |
| 2026-11-08 | `extraction/` reuses `ingestion` via an editable uv path dependency (one RawStore, no copy) | `extraction/pyproject.toml` |
| 2026-11-08 | Layout family decided from table header cells, never file name/date; `unknown` fails the run. Sixth family F found; B corrected to 19 files | `classify.py`, data-sources §7.1 |
| 2026-11-08 | Tests never use real CDSCO files: they build tiny PDFs themselves; real-archive checks are local integration tests | `extraction/tests/` |
| 2026-11-08 | Family-B columns matched by the header's x-positions, not by cell count; split cells merged, repeated lines dropped | `family_b.py` |
| 2026-11-08 | Portal batch numbers drop leading zeros and turn dashes into `?`: Phase 3 joins must normalise both | data-sources §1b |
| 2026-11-09 | One table engine for all families: the header row defines the fields, each family is a vocabulary; unknown header cells kept as `other_*` and reported | `table_parser.py` |
| 2026-11-09 | Bronze field names shared across families where the meaning is the same (`failure_reason`); "Drawn By" and "Reported by" stay separate | `rows.py` |
| 2026-11-09 | Spurious rows (families C, F) name the manufacturer printed on the fake label, usually the copied brand: Phase 3 / Phase 7 must never count them against that company | `family_f.py`, extraction report §2.3 |
| 2026-11-09 | Family D's combined cell: kept as printed (`batch_details`) and split at CDSCO's own labels; a cell with a repeated label (multi-part pack) is not split and gets a warning | Harith; `family_d.py` |
| 2026-11-09 | Engine: a repeated header replaces the column positions (latest header wins) | `table_parser.py` |
| 2026-11-09 | Family E repeats family A's 16 vaccine batches (and 2019+ are in the portal): Phase 3 must treat them as one finding per batch | extraction report §2.6 |
| 2026-11-09 | Every record carries provenance; `source_url` is the downloaded CDSCO PDF URL; extraction refuses bytes that don't match the sidecar SHA-256 | `extract.py` |
| 2026-11-09 | Confidence = high only if required fields are present and well-formed and the parser raised no warning. Placeholders (`NIL`) and Excel day numbers count as low (the plan's rule); reasons keep parser problems apart from source values | `confidence.py`, extraction report §2.9 |
| 2026-11-09 | Engine warns on overprinted cells: 2+ pairs of different characters overlapping by half a character width | `table_parser.py` |
| 2026-11-09 | Family B vocabulary gains `Mfg Dt` / `Exp Dt` (missed in step 2); the archive test fails on any unknown header | `family_b.py`, `test_extract.py` |
| 2026-11-09 | pyarrow (used directly, explicit schema) writes bronze Parquet; one file per source PDF at its `raw/` key; one schema for all families | Harith; ADR 0007 |
| 2026-11-09 | Step 6 covers PDF records only; portal JSON → bronze (with `extraction_method = api`) is its own later step | Harith |
| 2026-11-09 | Parquet is read single-threaded from an Arrow buffer (`from_parquet`): Arrow's thread pools hung the process at exit on macOS | ADR 0007, extraction report §2.10 |
| 2026-11-10 | Eval-set labelling: pre-filled parser values checked against a picture of the PDF page (anchoring risk accepted; the guide's rule is to look before pressing Enter) | Harith; `docs/eval-set.md` |
| 2026-11-10 | Eval-set labels stay in git-ignored `data/eval-set/` with Harith's private backup; the repo holds only code, guide and a manifest of row IDs (ADR 0003) | Harith; `docs/eval-set.md` §2 |
| 2026-11-11 | Eval-set labels made by AI-assisted double reading (parser vs Claude reading the row picture blind); Harith decides every disagreement; reported as such | Harith; `docs/eval-set.md` §1b |
| 2026-11-11 | Labelling tool: keys typed before a question appears are discarded; rows answered in under 8 s are asked again | `label.py` |
| 2026-11-12 | Scoring rule: values compared with spaces and line breaks removed; a wrong value counts as FP and FN; blank labels count only invented text; unreadable labels not scored; pooled (micro) over all values | `evaluate.py`, extraction report §3.1 |
| 2026-11-12 | Phase 2 checkpoint: no re-scope (F1 99.6%, no scanned CDSCO PDFs) | extraction report §3.1 |
| 2026-11-12 | Phase 2 closed (approved by Harith) | — |
| 2026-11-12 | Phase 3 approved; starts with step 0, portal JSON → bronze | Harith |
| 2026-11-12 | Spark reads/writes RustFS through hadoop-aws 3.5.0 (S3A) + AWS SDK bundle (686 MB, local only; CI never downloads it); PySpark pinned `>=4.2.1,<4.3` to keep Hadoop 3.5.0 | Harith; ADR 0008 |
| 2026-11-12 | `spark/` uv project; one shared Spark session in tests (Spark allows one per process); CI installs Java 17 (Temurin) explicitly rather than trusting the runner's default JDK | `spark/`, `lint.yml` |
| 2026-11-12 | `prefetch.py`: resumable, checksum-verified downloader for the 686 MB AWS SDK jar, after a single-stream download kept failing on a slow link; primes `~/.m2` so Spark's own resolver finds it there first | ADR 0008 |
| 2026-11-12 | `RUSTFS_ENDPOINT` in `s3a_conf()` defaults to `http://localhost:9000`, matching `RawStore.from_env()` (a test first caught the mismatch: `.env` never sets this variable) | `session.py` |
| 2026-11-12 | Portal rows: `extraction_method = api`; provenance = raw key + SHA-256, request URL, fetch time, row position; field names shared with PDF records (NSQ `str_product_name` → `generic_name`); newest response per month | ADR 0004 update, `portal_bronze.py` |
| 2026-11-12 | `label --review`: Harith decides each disagreement (1 = parser, 2 = second reader, or types it); the label records which values a person decided | `label.py` |
| 2026-11-10 | Eval sample: up to 12 random rows per PDF (seed 2026, 309 rows); split fixed at sampling time by whole PDF, per family (test/validation/train 20/20/60); row ID = file SHA-256 + page + S.No | `eval_set.py`, `eval/manifest.csv` |
| 2026-11-12 | Whitespace normalization keeps every line break, including blank-line separators (a portal manufacturer field genuinely separates maker from marketer this way); letter-spacing ("A s s a y") deferred to its own pass, as real examples mix spaced/normal text and aren't always one character per gap | `clean_text.py` |
| 2026-11-12 | Fixed: 9 portal NSQ rows (2019-01) with a wrong `batch_no` (stale/reused, or a stray trailing comma), by re-deriving batch_no/mfg_date/expiry_date/manufacturer from the embedded combined cell; trigger is the label pattern, not hardcoded row numbers | Harith; `fix_portal_batch.py` |
| 2026-11-12 | `split_combined_cell()` strips a whole run of trailing commas/whitespace (`strip(" \t\n,")`), not just one (`removesuffix(",")`): one real row has a double comma before the next label. Checked: Phase 2's shipped family_d.py / PDF bronze is unaffected (0 of 77 rows have the issue), so it is left as-is | `fix_portal_batch.py` |
| 2026-11-12 | Date parsing (step 3) scoped to portal dates first: one clean shape covers 100% of real values, vs 30-40 PDF shapes needing their own pass; `mfg_date_parsed`/`expiry_date_parsed` added alongside the original text (not overwritten), plus a nullable `dates_valid` flag that is never guessed | `parse_dates.py` |
| 2026-11-12 | `try_to_date()`, not `to_date()`: Spark 4's ANSI mode makes `to_date()` crash the whole job on one unparseable value instead of returning null; found before shipping, not during a real run | `parse_dates.py` |
| 2026-11-12 | PDF date formats added one at a time, each checked unambiguous against every real value first (zero cross-matches between all 5; day-first for DD-MM-YYYY proven by 17 real values with a day over 12); covers 88.8%/88.6%, rest deferred | `parse_pdf_dates.py` |
| 2026-11-12 | `plausible_year()`: any parsed date outside 1990-2049 (confidence.py's own range) becomes null. Found because Java's lenient parser reads a doubled dash as a year sign (`"Apr--2026"` -> year -2026, crashes on conversion to a Python date) rather than failing to parse; applied to both date modules for consistent safety, confirmed by a mutation check | `parse_dates.py`, `parse_pdf_dates.py` |
| 2026-11-13 | Step 4 split into three pieces (dosage form, strength as a list, brand vs generic only where clear); product names are too inconsistent for one regex splitter, and a null is better than a wrong split | Harith |
| 2026-11-13 | Dosage form: whole-word vocabulary + abbreviations (not after a hyphen); several forms -> null except "Injection wins" (proven on all 62 real cases); Sachet/Respules/Rotacaps excluded, Bolus added | `dosage_form.py` |
| 2026-11-13 | Strengths: a list of every mention as printed (repeats kept, since real combinations share values); slash = "per" only before ml or per-gram; bare ml skipped (bottle size), bare g only for injections, numbers glued to a letter skipped | `strength.py` |
| 2026-11-13 | Brand/generic split only where exactly one bracket group exists AND a pharmacopoeia marker (IP/BP/USP) sits on exactly one side; a dosage-form-word signal was tried first and rejected (29.5% ambiguous vs 1.9%) | `brand_generic.py` |
| 2026-11-13 | Found by reading the real split output, not assumed safe: a "brand" that was just the strength (52 cases) or a second synonym description ("Ringer Lactate Solution for Injection", 29 cases) - both rejected by name, not by blocklist, so the rule generalizes | `brand_generic.py` |
| 2026-11-13 | Manufacturer step 5 split into 3 pieces (clean name, RapidFuzz match, Harith reviews borderline pairs); piece 1 cuts the address at the first comma or legal suffix, keeps an "(A Unit of...)" aside as part of the name, and leaves the 0.9% with no boundary signal whole rather than guessed | Harith; `manufacturer_name.py` |
| 2026-11-13 | Manufacturer name case is left exactly as printed, not title-cased: some ALL CAPS names are real acronyms ("JKMSCL") that title-casing would wrongly mangle; case-insensitive comparison is left to RapidFuzz's own processor in piece 2 | `manufacturer_name.py` |
| 2026-11-13 | RapidFuzz threshold 98 for automatic merging, 95-98 for human review, nothing below: chosen by reading real pairs in every band (95-98 mixes real matches with clear false ones like RPL vs ZRS at 95.1) | `manufacturer_cluster.py` |
| 2026-11-13 | `process.extract` with a score_cutoff, not `process.cdist`: identical results on the real archive, no n x n matrix, and no numpy dependency (so no new library needed approval). Found while fixing uint8 rounding, which silently auto-merged 34 pairs that should have gone to review | `manufacturer_cluster.py` |
| 2026-11-13 | The 260 borderline pairs are sorted by what differs (spacing / misspelt common word / distinctive name) rather than reviewed as one list: 100 are mechanical and safe as batches, 160 need judgement | `manufacturer_review.py` |
| 2026-11-13 | Review pairs are NOT grouped into clusters for one decision each: grouping chains different companies together (Apple/Apex/APT Formulations), so one "yes" would merge all three. Every judgement pair stays its own question | `manufacturer_review.py` |
| 2026-11-16 | Spark's RPC pinned to loopback (`spark.driver.bindAddress` / `spark.driver.host` = 127.0.0.1): the Mac's hostname resolves to the *inactive* `bridge0` interface (192.168.3.1), so every driver<->executor message waited out a 10 s `NettyRpcEnv` timeout. Found by reading the benchmark log (22% CPU over 9 minutes = waiting, not working), not guessed | `session.py` |
| 2026-11-16 | `local[4]`, not `local[*]`, plus an explicit `spark.driver.memory=2g`: on this 8 GB machine `local[*]` = 8 task slots started ~13 Python UDF workers (50-190 MB each) and peaked at 3,159 MB. In local mode the executor *is* the driver JVM, so `spark.executor.memory` is ignored and `driver.memory` is the whole heap | `session.py` |
| 2026-11-16 | S3A reader pinned to `fs.s3a.input.stream.type=classic`: Hadoop 3.5.0 defaults to the analytics-accelerator reader, which against local RustFS took 39.5 s for a 31 KB object and hit the 60 s timeout on 8 others, while pyarrow read the same objects in 0.02 s. Key and its values (classic/prefetch/analytics) verified inside hadoop-aws-3.5.0.jar | `session.py` |
| 2026-11-16 | The three settings together: Spark pipeline 435.9 s -> **53.2 s**, total 444.7 s -> **62.2 s**, peak 3,159 MB -> **2,450 MB**, 0 S3 timeouts, 0 RPC stalls, CPU 35% -> 102% (computing instead of waiting). pandas unchanged at 12.6 s / 423 MB. 230 tests pass. Figures move to `docs/benchmarks.md` when step 9 is finished | step 9 (in progress) |
| 2026-11-16 | Earlier Spark runs crashed the Docker VM (all four containers `Exited (255)`) because another project's `opspilot-control-plane` held 3.41 GiB of the 5 GB Docker allowance; DrugWatch's own four services use 245 MB together. Docker Desktop's memory setting is a ceiling, not a reservation: with OpsPilot stopped the VM holds ~450 MB, so the 5 GB setting was left alone | — |
| 2026-11-18 | Phase 3 closed (all 3 done-when criteria met); Phase 4 approved | Harith |
| 2026-11-18 | Silver → Postgres is loaded by pyarrow + psycopg `COPY`, not Spark JDBC: Phase 3's own benchmark measured Spark at ~2 min / 2.7 GB for this table vs 1.2 s here, and dbt-postgres ships a driver anyway. New `warehouse/` uv project so `dbt/` stays a pure dbt project | Harith; ADR 0011 |
| 2026-11-18 | The loader reads silver through `drugwatch_quality.silver`, not its own copy, so the GE gate and the load see the same rows in Phase 5's validate → load DAG | ADR 0011 |
| 2026-11-18 | Staging keeps silver's types (`date`, `boolean`, `text[]`) and carries no constraints: those rules go in dbt tests, where a failure is a named report on queryable data, not a load-time crash | `warehouse/src/drugwatch_warehouse/schema.py` |
| 2026-11-18 | dbt builds into named schemas (`dbt_staging`, `dbt_intermediate`, `gold`) via a `generate_schema_name` override, never into `staging`, which the loader owns | `dbt/macros/generate_schema_name.sql` |
| 2026-11-18 | Staging models are views, and `sample_id` is an md5 of the provenance triple `(source_key, page, row_index)` — unique across all 7,126 rows and stable across rebuilds, unlike a row number | `stg_nsq_sample.sql` |
| 2026-11-18 | dbt telemetry switched off (`send_anonymous_usage_stats: false`) | `dbt/dbt_project.yml` |
| 2026-11-18 | dbt auto-loads the repo-root `.env` (`load_dotenv(find_dotenv(usecwd=True), override=False)`), so no `--env-file` is needed inside the repo; a shell variable still wins, and CI has none | `dbt/profiles.yml` |
| 2026-11-18 | Step 3 split into 3 pieces (star schema / state + lab_type / marts), like Phase 3 step 5 | Harith |
| 2026-11-18 | `dim_drug`'s grain is the printed product name, measured: no product name carries two different dosage forms, generic/brand names or strength lists (0 of 7,126). Differently-printed names are NOT merged without the same reviewed evidence Phase 3 used for manufacturers | `dim_drug.sql` |
| 2026-11-18 | The fact enforces the ethics rules itself: spurious rows carry no `manufacturer_id` (name kept in `name_on_pack`), and provenance (file, page, SHA-256, URL) travels into gold | `fact_nsq_sample.sql` |
| 2026-11-18 | Dimensions hold no counts, and `dim_date`'s range is derived from the data rather than hardcoded | `dim_manufacturer.sql`, `dim_date.sql` |
| 2026-11-18 | ⏳ OPEN: `drug_class` (§8.1) has no source in the archive; `mart_drug_class_failures` (§8.2) is blocked until Harith decides how (or whether) to classify medicines | — |
| 2026-11-18 | The manufacturer's state comes from a reviewed vocabulary seed matched against the address, and resolves to NULL whenever two states match (a village called Kerala sits in Gujarat; "Delhi-Mathura Road" is in Haryana) | `seeds/india_state_alias.csv`, `int_manufacturer_state.sql` |
| 2026-11-18 | Addresses are cut at a marketer marker before matching (`mrkt`/`marketed`/`mrk`/`mkt`/`markt`, counted as whole words); `market` is excluded because it is part of real addresses | `int_manufacturer_state.sql` |
| 2026-11-18 | `Raj.` is NOT in the state vocabulary: normalisation drops the dot, and a real Haryana address contains the word "Raj" | `india_state_alias.csv` |
| 2026-11-18 | ⏳ OPEN: 820 of 2,609 companies have no state; 653 print a PIN code, so a PIN-prefix mapping is the next largest gain but needs a reference table and Harith's OK (2-digit prefixes are ambiguous for every split state) | — |
| 2026-11-19 | PIN → state is a map LEARNED from the 1,421 addresses that name their state (3-digit prefix, unanimous, ≥3 companies), not a hardcoded postal table: writing India's prefixes from memory would be inventing reference data, and 2-digit prefixes are ambiguous for every split state | `int_pin_prefix_state.sql`, ADR-worthy note in PROGRESS |
| 2026-11-19 | The PIN map is validated by holdout (learn on half the known rows, predict the other): 99.78% at ≥3 vs 99.59% at ≥2. Checking it against the rows it learned from was circular and reported a meaningless 100% | `analyses/pin_prefix_holdout.sql` |
| 2026-11-19 | The PIN is read from the ORIGINAL address with only whitespace allowed inside it, so "Khasra No. 140-141" and "393/394" are not mistaken for postal codes | `int_manufacturer_address.sql` |
| 2026-11-19 | A state name followed by road/highway/bypass/marg/NH is a road name, not a location ("Delhi Road, Sonepat" is Haryana): 10 addresses | `int_manufacturer_state.sql` |
| 2026-11-19 | `lab_type` (Central/State) travels on every fact row, and the lab's state is kept strictly apart from the manufacturer's: 498 findings tested in West Bengal were made in Himachal Pradesh, so grouping by the reporting state would measure testing effort, not drug quality | `int_reporting_lab.sql`, `fact_nsq_sample.sql` |
| 2026-11-19 | Lab abbreviations live in a seed WITH their expansions (CDL/CDTL/RDTL = CDSCO's own; DTL/SDTL/DCL/FDL/FDAL/FDTL/BDCL = state), so the table can be checked by someone who does not know them | `seeds/lab_type_marker.csv` |
| 2026-11-19 | The reviewed lab-city seed is cross-checked against reporter strings that name both city and state: 15 of 33 cities confirmed, 0 disagreements; the CSV records which rows the archive can confirm | `analyses/lab_city_crosscheck.sql` |
| 2026-11-19 | `MDTL` left unclassified (6 rows): whether a Mini Drug Testing Laboratory is state-run could not be established without guessing | `lab_type_marker.csv` |
| 2026-11-19 | `mart_repeat_offenders` (§8.2) renamed `mart_repeat_reported_manufacturers`, counting alert MONTHS and ranked with DENSE_RANK: "offender" is a verdict and CLAUDE.md §6 forbids it | `mart_repeat_reported_manufacturers.sql` |
| 2026-11-19 | All rolling/trailing windows are RANGE windows over dates, not ROWS: CDSCO published in 101 of the 111 months spanned, and a ROWS window differs on 209 of 85,924 rows | `mart_manufacturer_trend.sql`, `mart_ml_features.sql` |
| 2026-11-19 | `mart_ml_features` verified by recomputing every one of its 85,924 rows independently of the model's own windows: 0 wrong features, 0 wrong labels, 0 leaked labels. Last trainable cutoff 2026-03; 14.2% positive | `mart_ml_features.sql` |
| 2026-11-19 | §12's "spurious association" feature cannot exist by design (spurious findings carry no manufacturer_id), and "share by drug class" waits on the drug_class decision | `mart_ml_features.sql` |
| 2026-11-19 | 38 dbt tests (31 generic + 7 singular), each mutation-checked: a deliberately broken model is shown to fail the specific test meant to catch it, including label leakage (3,110 rows) and spurious attribution (17 rows) | `dbt/tests/`, `_marts__models.yml` |
| 2026-11-19 | `assert_expiry_after_mfg` is a consistency check (impossible dates are allowed, but only when `dates_valid` marks them), because CDSCO really does print 17 impossible date pairs | `tests/assert_expiry_after_mfg.sql` |
| 2026-11-19 | The category vocabulary is restated in the test, not imported: a test that reads its expectations from the code under test cannot fail | `tests/assert_failure_categories_in_vocabulary.sql` |
| 2026-11-19 | dbt tests gate the pipeline, not CI: they need Postgres plus the loaded silver, so CI runs only `dbt parse` and `dbt build` stays a local/Phase 5 step | `.github/workflows/lint.yml` |
| 2026-11-19 | dbt docs generated from the model descriptions; lineage is derived from `ref()`/`source()` so it cannot disagree with the code. 19/19 models and seeds documented, 31% of columns (passthrough columns left undescribed on purpose) | `dbt docs generate`, `_intermediate__models.yml` |
| 2026-11-19 | Phase 4 done-when met: `dbt build` = 63 nodes, 0 errors (3 seeds, 16 models, 44 tests). Two §8.2 marts deferred with reasons (§8.2 calls its list "examples") | PROGRESS Phase 4 |
| 2026-11-19 | Phase 4 closed (approved by Harith) | — |
| 2026-11-19 | Phase 5 approved | Harith |
| 2026-11-19 | Airflow runs on the HOST as an `orchestration/` uv project, not in Docker: Airflow (~1.5 GB) plus a Spark run (2.7 GB measured) would be ~4.5 GB of Docker's 5 GB VM, which already died once in Phase 3. Metadata goes in a new `airflow` database in the existing Postgres | Harith; ADR 0012 |
| 2026-11-19 | A DAG task is a documented `uv run --env-file ../.env` command from CLAUDE.md §10, built by one factory: reproducible by hand, and secrets reach the task from `.env` without Airflow ever holding them | `orchestration/src/drugwatch_orchestration/tasks.py` |
| 2026-11-19 | DAGs live in `orchestration/`, not `ingestion/` as CLAUDE.md §9 said: every phase's project feeds the DAGs, so burying the orchestrator in the first one would make it depend on all the others | ADR 0012, CLAUDE.md §9 |
| 2026-11-19 | Airflow 3.4 notes: `dags list` reads the DB (a new DAG needs `dags reserialize`), `DagBag` no longer takes `include_examples`, and `dags test` prints a harmless MissingGreenlet traceback at teardown with either Postgres driver | PROGRESS Phase 5 step 0 |
| 2026-11-19 | The monthly DAG asks the portal for the interval's month AND the previous one with `--refresh`, because state labs report late and a month's JSON keeps changing; unchanged bytes are never re-stored, so the second ask is free | `dags/monthly_pipeline.py` |
| 2026-11-19 | Schedule is the 10th at 03:00, not the 1st: CDSCO publishes a month's alerts during the following month | `dags/monthly_pipeline.py` |
| 2026-11-19 | Validation runs BEFORE the load, and `max_active_runs=1` because every task writes shared state (two runs = two Spark jobs overwriting one silver prefix) | `dags/monthly_pipeline.py` |
| 2026-11-19 | Whole pipeline measured at 240.3 s (build_silver 152.9 s of it); `benchmarks.md`'s ~10-minute figure for `build_silver.main()` was stale (pre-`session.py` tuning) and is corrected | `docs/benchmarks.md` |
| 2026-11-19 | ⏳ OPEN: "check for new alerts" is implicit — a no-change run still costs ~4 min. Short-circuiting needs the structured run log from step 5, not stdout parsing | PROGRESS Phase 5 step 1 |
| 2026-11-19 | The seven processing tasks are built once in `pipeline.processing_chain()` and shared by both DAGs (no TaskGroup, which would rename task ids and orphan run history) | `orchestration/src/drugwatch_orchestration/pipeline.py` |
| 2026-11-19 | A backfill never rebuilds part of silver: `build_silver` overwrites the whole table, and clustering manufacturers over a subset would produce different canonical names than the full archive | `dags/backfill_pipeline.py` |
| 2026-11-19 | Parameter errors are permanent, not transient: `check_month_range` runs first with `retries=0`, so a bad range fails in 11.8 s instead of 15 minutes of backoff | `pipeline.py` |
| 2026-11-19 | `op_kwargs={"params": "{{ params }}"}` renders Jinja to a STRING: the gate failed with a TypeError instead of its own explanation. Context keys are injected by signature instead | `dags/backfill_pipeline.py` |
| 2026-11-19 | Observed: 3 retries with backoff capped at 15 min recovers ~7-15 min of transience (the downloads did), not a sleeping laptop (the extractions did not). Hence step 4's email, and a non-sleeping VM in Phase 12 | PROGRESS Phase 5 step 2 |
| 2026-11-19 | Alerting policy: one email per task that fails after retries are exhausted, nothing for recovered attempts and no success summaries. Step 2's failed backfill would send 2 emails, not 12 | Harith; `notifications.py` |
| 2026-11-19 | The failure email carries the command to reproduce the task by hand, which is only possible because every task is a documented command (ADR 0012) | `notifications.failure_message()` |
| 2026-11-19 | Airflow's SMTP connection is built from the repo's own SMTP_* variables and exported as `AIRFLOW_CONN_SMTP_DEFAULT`, so Mailpit and Brevo differ only by `.env` and Spring Boot reads the same credentials | `config.smtp_connection()` |
| 2026-11-19 | Verified by running it: final failure -> 1 email with the real error in the body; a task that fails then succeeds -> 0 emails | PROGRESS Phase 5 step 4 |
| 2026-11-19 | The run log reads every figure from a structured source — RustFS, Postgres, dbt's run_results.json, and each task recording itself — never from scraped stdout | `orchestration/src/drugwatch_orchestration/run_log.py` |
| 2026-11-19 | dbt's run_results.json is rejected when older than the run that is being logged; unknown figures are stored as null, never as 0 | `run_log.dbt_node_counts()`, `added_since()` |
| 2026-11-19 | Bug found by comparing with `inventory`: filtering out `.json` keys hid the portal's raw snapshots (213 of 331 files). The run log counts sidecars, the store's own "complete" marker | `run_log.raw_file_count()` |
| 2026-11-19 | Bug found by reading the row: Airflow's `TaskInstanceState` enum stringifies to `TaskInstanceState.SUCCESS`, so a perfect run was logged as failed. `state_name()` stores the value, with a regression test using the real enum | `run_log.state_name()` |
| 2026-11-19 | Phase 5 done-when met: both DAGs run end to end unattended, re-runs create no duplicates at any layer, alerting and run log in place | PROGRESS Phase 5 |
| 2026-11-19 | Phase 5 closed (approved by Harith) | — |
| 2026-11-19 | Phase 6 approved; price-gap dashboard deferred (no price data downstream of `raw/`), `drug_class` to get a reviewed vocabulary, Jupyter+matplotlib adopted, no map of India | Harith; ADR 0013 |
| 2026-11-19 | Exploration reads gold in a READ-ONLY transaction, proven by a test expecting `ReadOnlySqlTransaction`; notebooks are committed with outputs cleared, enforced by repo-checks.sh | `analytics/src/drugwatch_analytics/gold.py`, ADR 0013 |
| 2026-11-19 | Finding: NSQ findings track TESTING EFFORT (findings vs reporting labs r = 0.964 by year), so no dashboard may show a bare findings-per-month line | `docs/analytics-findings.md` §1 |
| 2026-11-19 | Finding: 58% of manufacturers appear exactly once (median 1 finding), so a top-N chart describes 10 of 2,609 companies | `docs/analytics-findings.md` §2 |
| 2026-11-19 | Finding: lab state differs from manufacturer state in 92.7% of findings where both are known — two charts, never one map | `docs/analytics-findings.md` §4 |
| 2026-11-19 | Superset runs in Docker (unlike Airflow): a plain web app with no Spark beside it, and the one service Phase 12 exposes to the internet | `docker-compose.yml` |
| 2026-11-19 | "Superset reads gold only" is enforced by the `superset_reader` grant, including ALTER DEFAULT PRIVILEGES because dbt recreates gold tables on every build; proven through Superset's own API, not just psql | `infra/postgres/superset_reader.sql`, `infra/superset/smoke_test.sh` |
| 2026-11-19 | apache/superset:6.1.0 ships NO Postgres driver; and its `pip` is the system one while `python` is /app/.venv/bin/python, so the driver must be installed at the venv's interpreter | `infra/superset/Dockerfile` |
| 2026-11-19 | RustFS had grown to 2.1 GB of cache for 170 MB of data (restart reclaims it); Superset settled at 213 MB, so all five services use ~650 MB of the 4.8 GB VM | PROGRESS Phase 6 step 2 |
| 2026-11-19 | ⏳ Phase 12 must enable TALISMAN_ENABLED with a CSP before Superset is public; the missing-CSP warning is left unsilenced as the reminder | `infra/superset/superset_config.py` |
| 2026-11-19 | Dashboards are provisioned from code over Superset's API, never clicked: one that exists only in Superset's database cannot be rebuilt, reviewed or deployed | `infra/superset/build_manufacturer_dashboard.py` |
| 2026-11-19 | Dashboard figures that gold lacked became dbt marts, not Superset virtual datasets: `mart_monthly_reporting` keeps findings and reporting-lab counts in ONE mart so the misleading chart is not the easier one to build | `dbt/models/marts/` |
| 2026-11-19 | A Superset chart needs a stored `query_context` as well as `params`, or anything asking it for data server-side fails (Phase 9 alerts included) | `build_manufacturer_dashboard.py` |
| 2026-11-19 | Chart verification POSTs the stored context to /api/v1/chart/data, as a dashboard does; GET /api/v1/chart/{id}/data/ returns an unexplained 400 for API-provisioned charts | `infra/superset/verify_charts.py` |
| 2026-11-19 | CI now lints `infra/` with a pinned ruff via uvx: those scripts belong to no uv project, so the per-project matrix never saw them | `.github/workflows/lint.yml` |
| 2026-11-19 | The states dashboard's headline (92.7% tested in a different state) is a dbt mart, not dashboard prose: a number written into text is right the day it is written and silently wrong after | `dbt/models/marts/mart_lab_vs_maker_state.sql` |
| 2026-11-19 | "Made here" and "tested here" are separate, equal-sized charts that must never be summed, and the state-laboratory subset gets its own column as the honest answer to "what did this state's own testing find" | `infra/superset/build_states_dashboard.py` |
| 2026-11-19 | Superset provisioning helpers extracted to `dashboards.py` when the second dashboard needed them, before copies could drift | `infra/superset/dashboards.py` |
| 2026-11-19 | A categorical x-axis must not carry a time grain (it would truncate a state name to a month), and bar charts need `x_axis_sort` or the largest states are drawn alphabetically | `dashboards.query_context()`, `build_states_dashboard.py` |
| 2026-11-19 | Verification covers the DATA each chart returns, not its appearance: bar order and layout need a human with a browser | `infra/superset/verify_charts.py` |
| 2026-11-19 | The spurious mart carries NO manufacturer_id and names the copied brand `name_printed_on_the_pack`, so the ethics rule is enforced by the schema rather than by wording: verified 0 columns mention a manufacturer | `dbt/models/marts/mart_spurious_report.sql` |
| 2026-11-19 | The spurious dashboard states its own scale (77 of 7,126 findings, 2024-04 onwards) and asks the reader not to treat the monthly chart as a trend | `infra/superset/build_spurious_dashboard.py` |
| 2026-11-19 | `source_url` is `not_null`-tested on the spurious mart: a counterfeit finding must never be shown without the CDSCO document that reports it | `_marts__models.yml` |
| 2026-11-20 | Public access is a hand-built 21-permission role, NOT `PUBLIC_ROLE_LIKE=Gamma`: Gamma grants anonymous `can_write on Chart`/`Dashboard`, `can_delete_embedded` and user registration | `infra/superset/configure_public_role.py` |
| 2026-11-20 | Datasource access is granted per gold dataset, so a dataset added later is invisible to the public until granted; the script also removes anything not on its list | `configure_public_role.py` |
| 2026-11-20 | "Filters working" genuinely requires `can_write on DashboardFilterStateRestApi` (Superset stores filter selections server-side); listed as an explicit exception | `configure_public_role.py` |
| 2026-11-20 | The anonymous test must not follow redirects: urllib followed FAB's redirect to /login/ and reported that a stranger could list users | `infra/superset/public_access_test.py` |
| 2026-11-20 | `superset init` does not reset the Public role (21 permissions before and after), so a future superset-init cannot quietly reopen the instance | PROGRESS Phase 6 step 4 |
| 2026-11-20 | Dashboards are committed as YAML (`infra/superset/assets/`) and the import path is tested: Superset's importer needs the top-level directory its exporter adds, or the import dies mid-JSON-decode | `infra/superset/export_assets.py`, `import_assets.sh` |
| 2026-11-20 | The export refuses to write if the real reader password appears in the bundle; Superset masks it as XXXXXXXXXX, verified 0 matches | `export_assets.py` |
| 2026-11-20 | `mart_data_freshness` reads Phase 5's run log through a dbt `ops` source, so dashboards can show their own freshness without Superset being granted the ops schema; it reports the latest SUCCESSFUL run | `dbt/models/marts/mart_data_freshness.sql` |
| 2026-11-20 | ⏳ OPEN: Superset holds a corrupt `tables` row (id 8) that its API 404s on while its uniqueness check sees it, blocking the freshness panel. Cache, restart, permissions and re-import all ruled out. Needs Harith's OK to delete the row | PROGRESS Phase 6 step 5 |
| 2026-11-20 | ✅ RESOLVED: Superset's dataset and chart list APIs filter by `datasource_access`, and admin's `all_datasource_access` does NOT cover a dataset no role holds a grant for - such a dataset 404s while its uniqueness check still sees it. Granting it fixes it; `ensure_dataset` now says so instead of raising a 422 | `infra/superset/dashboards.py` |
| 2026-11-20 | The "Data last updated" panel is one chart shared by all three dashboards, so two pages can never disagree about the data's age | `dashboards.ensure_freshness_chart()` |
| 2026-11-20 | `drug_class` has no source in CDSCO, so it comes from a reviewed vocabulary of 215 ingredient phrases (80.6% of findings), held as an **array** because 7.9% of findings carry 2-4 classes | ADR 0014 |
| 2026-11-20 | The vocabulary holds phrases, not words: a word-level one files "Atorvastatin Calcium" as a mineral supplement, because the calcium is the salt the statin is formulated as | `drug_class.py` |
| 2026-11-20 | CDSCO also tests cotton wool, gauze, syringes, hand sanitiser, soap and hair colour, so 4 of the 26 classes exist to say "not a medicine" - charting a steroid-contaminated beauty cream as a Corticosteroid would invert the finding | ADR 0014 |
| 2026-11-20 | A test that rejects a reason which only restates its own class found 13 such reasons in my first draft ("NSAID.", "Vitamin."); they were rewritten, not exempted | `tests/test_drug_class.py` |
| 2026-11-20 | Harith reviewed the drug-class vocabulary: 213 of 215 accepted, `oxetacaine` and `menthol` rejected because each changes role with what it is combined with | `data/drug-class-review/decisions.jsonl` |
| 2026-11-20 | 🔍 A Superset dashboard with NO charts is invisible even to an admin - access is resolved through its charts' datasources - so a build that dies before attaching them leaves a dashboard whose slug is taken and which nothing can find | `infra/superset/attach_orphan_dashboard.py` |
| 2026-11-20 | `int_drug_class` is a table, not a view: three nodes read it and each was re-running the 5,651 x 213 regex cross join (~21 s apiece). Full `dbt build` 45 s -> 23 s | `int_drug_class.sql` |
| 2026-11-20 | Dashboard 3c's charts read summary marts rather than §8.2's month-grain mart, so the default reading is the safe one instead of depending on a remembered caveat | `mart_drug_class_summary.sql` |
| 2026-11-20 | ✅ Phase 6 signed off. Phase 7 approved with four decisions: scikit-learn declared (ADR 0015), MLflow in Compose (ADR 0016), a stricter winning bar, two extra features | Harith |
| 2026-11-20 | Plan §12's baseline scores ROC-AUC 0.623, but ranking by `reports_24m` alone scores 0.687 - so "beats both baselines" could be satisfied against a straw man. The bar is now all three, on PR-AUC, with a CI | PROGRESS Phase 7 |
| 2026-11-20 | 44% of manufacturers (1,151 of 2,609) were first reported during the test window and have no rows before their first finding, so the score cannot answer "is this company risky?" - only "will one already in the archive be reported again?" | model card |
| 2026-11-20 | I expected companies quiet for 24 months to be certain negatives; they are 8.1% positive and supply 557 of 3,534 test positives. They stay in, reported separately | `mart_ml_features` |
| 2026-11-20 | `log_artifact` reports success even when the server cannot reach its artifact store, so the smoke test reads the artifact back from RustFS byte for byte | `drugwatch_ml/smoke_test.py` |
| 2026-11-20 | A date-based train/test split leaks here: a training row's label covers the 6 months AFTER its cutoff, so training to 2025-03 shares 5 of the 6 months a 2025-04 test row is scored on. `Fold` refuses to exist without the embargo | `ml/.../splits.py` |
| 2026-11-20 | 1,071 of 2,242 test-window companies (48%) never appear in training, so every metric must be reported for seen and new companies separately | PROGRESS Phase 7 step 1 |
| 2026-11-20 | The embargo discards 6,562 labelled rows (9.2%); the figure is printed by `show_protocol` so it stays a decision someone looked at | `drugwatch_ml/show_protocol.py` |
| 2026-11-20 | The archive's trailing 12-month volume correlates 0.855 with calendar time, so it is a clock, not a feature. It enters only as a ratio (`share_of_archive_reports_12m`, -0.180) | `mart_ml_features.sql` |
| 2026-11-20 | A test rejects any feature correlating >0.7 with the cutoff; it found `central_lab_share_12m` at -0.534 (state labs grew relative to central ones). Kept as a real company feature, pinned and noted for the model card | `ml/tests/test_features.py` |
| 2026-11-20 | 🐛 `filter (where drug_class = 'Unclassified')` counted 0 of 1,382 findings: dim_drug stores an EMPTY ARRAY, not that string. A constant feature passes every range check, so two tests now fail on one | `assert_ml_feature_shares_are_valid.sql` |
| 2026-11-20 | 🐛 `NULL > 0` is NULL and `NULL is distinct from false` is TRUE, so a null-state check flagged all 46,296 quiet rows as corrupt. The test was wrong, not the mart | `assert_ml_feature_shares_are_valid.sql` |
| 2026-11-20 | The bar is PR-AUC 0.373 (logistic regression), not the plan's rule at 0.185. Ranking by `reports_24m` alone beats the plan's rule on every metric with no fitting | step 3 |
| 2026-11-20 | The two best baselines tie on ROC-AUC (0.728 vs 0.726) and separate on PR-AUC (0.323 vs 0.373), which is why PR-AUC decides: with 13% positives, ROC-AUC is dominated by ordering easy negatives | step 3 |
| 2026-11-20 | Logistic beats the count ranking by +0.034 PR-AUC, 95% CI +0.012..+0.050, so the bar is not a coin flip. Decision C's significance rule applied to the baselines too | `run_baselines.py` |
| 2026-11-20 | Bootstrap CIs resample companies, not rows - a test shows row-level resampling gives a narrower interval than the evidence supports | `ml/.../metrics.py` |
| 2026-11-20 | LightGBM out of the box (PR-AUC 0.359) LOSES to logistic regression (0.373); tuned it reaches 0.383. Without tuning this phase would have failed its own bar | step 4 |
| 2026-11-20 | The winning settings are simpler than the defaults - 7 leaves not 31, 100 trees not 300, min_child_samples 100 not 20 - so the data supports a small regularised model. The 800-tree 127-leaf trial scored 0.289 | step 4 |
| 2026-11-20 | `scale_pos_weight=3.0` was chosen, which distorts the predicted probability. §4.3 shows it publicly as a probability, so step 5's calibration check decides whether it may be called one | `model.py` note 3 |
| 2026-11-20 | The model never split on `central_lab_share_12m`, the -0.534 calendar drifter, and did use `share_of_archive_reports_12m`, step 2's ratio replacement | step 4 |
| 2026-11-20 | 🐛 A 141-minute 'slow search' was the Mac sleeping, not the code: fits totalled 11s, gaps reached 3,214s at no CPU. CLAUDE.md §10 says to use `caffeinate -i`; I had not | step 4 |
| 2026-11-20 | ⚠️ TEST RESULT: LightGBM PR-AUC 0.385 vs logistic 0.373, difference +0.011 with 95% CI -0.004..+0.026. It beats the other two baselines clearly but is statistically TIED with a linear model | step 5 |
| 2026-11-20 | On precision@20 per month - the metric matching how a list is read - logistic is AHEAD: 0.754 vs 0.738 | step 5 |
| 2026-11-20 | The score is publishable as a probability (ECE 0.024) only because the reweighting was dropped on validation first; `scale_pos_weight=3.0` predicted 0.252 against a 0.126 base rate | `evaluate.py` |
| 2026-11-20 | Every decile under-predicts because the training base rate was 12.8% and the test period's is 16.0%. Needs monthly recalibration in Phase 9, not a refit | step 5 |
| 2026-11-20 | Seen-during-training PR-AUC 0.438 vs new-companies 0.269 (P@20 0.725 vs 0.408): the model is far weaker on the half of the archive it has never seen | model card |
| 2026-11-20 | Option A: ship LightGBM with the tie documented. SHAP comes free from a tree model and a documented negative result beats a win nobody checked | Harith |
| 2026-11-20 | SHAP confirms both step-2 judgement calls: `distinct_drug_classes_12m` is the 3rd most used feature and `share_of_archive_reports_12m` the 4th, while the -0.534 calendar drifter is used not at all | step 6 |
| 2026-11-20 | Public wording is a fixed 28-phrase vocabulary; a feature with no approved phrase raises rather than printing its column name. Five tests enforce CLAUDE.md §6 instead of documenting it | `ml/.../explain.py` |
| 2026-11-20 | The registered model carries its own limitations as tags, so Phase 8 reads the tie off the artifact rather than a commit message | MLflow `manufacturer-risk` v1 |
| 2026-11-21 | ONNX matches the original on 22,070 real test rows: max difference 1.37e-07, Spearman 1.000000, 0 inverted rows, identical top-20. `build_onnx` vetoes its own artifact otherwise | ADR 0017 |
| 2026-11-21 | 🐛 Comparing `argsort` outputs reported a changed ranking at zero real inversions: it measures tie-breaking, not order. Replaced with strict-pair inversions plus top-20 set equality | `onnx_export.py` |
| 2026-11-21 | 🐛 MLflow 3 rejects an unrecognised Host header, and a compose service name is not in its default allow-list, so risk-api got a 403 'DNS rebinding attack'. Listing only :5000 then broke the Mac's :5050 access | docker-compose.yml |
| 2026-11-21 | 🐛 SHAP's first call costs ~77ms against ~4ms after; it showed as a p99 of 558ms on a 5.6ms endpoint. The explainer is warmed at startup | `app.py` lifespan |
| 2026-11-21 | MLflow sits at ~1.87 GiB resident against the risk service's ~265 MiB on a 4.8 GiB VM; four default workers to one saved only ~0.2 GiB | docker-compose.yml |
| 2026-11-21 | A 100-row batch costs 0.07ms per row against 3.8ms for a single call (51x), because at 100 trees of 7 leaves the time is HTTP and JSON, not the model. Phase 9 should send one batch per page | `docs/benchmarks.md` §2 |
| 2026-11-21 | `/explain` costs only 1.9ms more than `/predict` - a dividend of step 4's small model; the 127-leaf candidate would have been far slower AND scored worse | step 5 |
| 2026-11-21 | Benchmark p99 is host noise on this hardware: 29ms to 371ms on one endpoint with no code change, and 2,426ms when run right after an image build. p50/p95 are stable | `docs/benchmarks.md` §2 |
| 2026-11-21 | ✅ Phase 8 signed off. Phase 9 approved with five decisions: Maven/Spotless/ArchUnit and no coverage gate (ADR 0018), pg_trgm search, Redis rate limiting, term-based watchlist, email verification | Harith |
| 2026-11-21 | Maven Central's search API reports Spring Boot 3.5.3; its own maven-metadata.xml says 4.2.0. Versions come from the metadata, not the index | ADR 0018 |
| 2026-11-21 | 40% of batch numbers carry spaces or punctuation (KA/018), but normalising collapses only 6,807 distinct values to 6,766 - and "Not applicable" is a batch number on 22 findings | step 2 design |
| 2026-11-21 | Actuator publishes config, env and a map of internal services by default; the API exposes health only, with no component detail, checked by three tests | `application.yaml` |
| 2026-11-21 | 🐛 Spring Boot 4 removed `TestRestTemplate`; `RestTestClient` replaces it and needs its own `spring-boot-resttestclient` module, which starter-test does not pull in | `ApplicationSmokeTest` |
| 2026-11-21 | The API's Postgres role can read gold and write only its own `app` schema: 17 gold tables readable, 0 writable, `staging` and `ops` invisible. Six tests ask the database the forbidden questions | `infra/postgres/api_role.sql` |
| 2026-11-21 | `alert_notifications` has a UNIQUE on (watchlist item, alert month), so a duplicate email is impossible in the database rather than unlikely in the code | `V1__app_tables.sql` |
| 2026-11-21 | 🐛 Spring Boot 4 split auto-configuration into per-technology modules: `flyway-core` alone never runs the migration, and fails as a bare "relation does not exist". It needs `spring-boot-flyway` | backend/pom.xml |
| 2026-11-21 | 🐛 Testcontainers 2.0 renamed every module with a `testcontainers-` prefix, and Boot 4's parent no longer manages their versions | backend/pom.xml |
| 2026-11-21 | The batch checker works on the real archive: `TETY01` typed without punctuation finds 7 findings of `TETY-01`, each with its CDSCO source link | step 2 |
| 2026-11-21 | The batch rule exists in Java and in SQL, so a test runs both over every published batch number and requires identical text - a disagreement would silently tell users their medicine is absent | `GoldContractTest` |
| 2026-11-21 | Verified on real data: batch GTE1350A appears both as a genuine finding (manufacturer named) and as spurious (manufacturer null, copied brand in nameOnPack) | step 2 |
| 2026-11-21 | The pg_trgm index is 11x faster when used (2.4ms vs 27.6ms) but Postgres prefers a seq scan at 5,651 rows; built by dbt as a post-hook so a monthly rebuild cannot drop it | `macros/search_indexes.sql` |
| 2026-11-21 | 🐛 `@ExceptionHandler(Exception)` swallows Spring's status-carrying exceptions, turning every 404 into "500, quote this reference" | `GlobalExceptionHandler` |
| 2026-11-22 | Registration answers 202 with byte-identical text whether or not the address is taken, and emails the owner instead - a public endpoint that says who has an account is an oracle | `AuthService` |
| 2026-11-22 | 🐛 Revoking every session and then throwing rolled the revocations back, so reuse detection silently did nothing. A security response must survive the rejection that triggers it | `noRollbackFor` |
| 2026-11-22 | Tokens are stored as SHA-256 of 256 random bits, not BCrypt: BCrypt's slowness is worth paying against a guessable password and pointless against random bits | `TokenHash` |
| 2026-11-22 | Once the filter chain exists an unknown path answers 401, not 404, which hides whether a path is absent or protected. Two test expectations were updated, not the code | `SecurityConfig` |
| 2026-11-22 | Actuator's mail health check opens SMTP on every poll and a failure flips the service DOWN, so a mail outage would restart a working API | `application.yaml` |
| 2026-11-22 | A watch needs a baseline or adding one emails the back catalogue: "telmisartan" matches most of 101 published months. V2 adds `since_alert_month`, defaulting to '9999-12' so a row without one notifies about nothing | `V2__watchlist_baseline.sql` |
| 2026-11-22 | A watch term is interpolated into a word-boundary regex, so anything a regex engine reads as syntax is refused at the edge rather than escaped later | `WatchTerm` |
| 2026-11-22 | The notification row is written before the email is sent, so the UNIQUE constraint makes a duplicate impossible; the stated cost is that a failed send is lost rather than retried | `WatchlistNotifier` |
| 2026-11-22 | Verified on the real archive: watch "telmisartan" baselined at 2026-09 sent nothing; backdated to 2026-07 it sent 2 emails (6 and 8 batches) and recorded 2 rows | step 4 |
| 2026-11-22 | 🐛 Java's HttpClient offers an HTTP/2 upgrade and sends the body chunked; uvicorn replies 422 with the body missing. The fallback reported "no score today", identical to an outage - a silent permanent failure. Pinned to HTTP/1.1 | `RiskClient` |
| 2026-11-22 | The risk endpoint tells a reader whether the model was trained on their company: 48% of the test window was not, and scores there are PR-AUC 0.269 against 0.438 | `RiskService` |
| 2026-11-22 | An unavailable score is null, never 0: a zero reads as "this company is safe", the opposite of "we do not know". Measured 165ms to fail with risk-api stopped | step 5 |
| 2026-11-22 | Cache keys carry the alert month, so a monthly load invalidates everything by itself - no flush job whose silent failure would serve last month's answers as current. 192ms cold to 17ms cached | `DataVersionKeyGenerator` |
| 2026-11-22 | 🐛 A generic JSON cache serializer returns LinkedHashMap, breaking every cached endpoint on its SECOND call. Two tests passed because they only checked a key existed | `CacheConfig` |
| 2026-11-22 | The rate limiter fails open: it fronts the batch checker, and failing closed would trade a real Redis outage for a hypothetical abuser | `RateLimiter` |
| 2026-11-22 | The caller is the socket address, never X-Forwarded-For: a limit an attacker can opt out of looks like protection and is not. Phase 12's proxy is where forwarded headers belong | `RateLimitFilter` |
| 2026-11-22 | Login and the watchlist are NOT IP-limited - a shared office address would lock everyone out of their accounts | `RateLimitHttpTest` |
| 2026-11-22 | The guest-token service account holds exactly ONE Superset permission (can_grant_guest_token on SecurityRestApi), confirmed in Superset's tables - a leaked password mints tokens for already-public dashboards and nothing else | `configure_embedding.py` |
| 2026-11-22 | The EmbeddedViewer role is built by COPYING Public's permissions, so tightening Public in Phase 12 tightens embedding too instead of two lists drifting | step 7 |
| 2026-11-22 | 🐛 An unconfigured dashboard sat in the allowlist with an empty UUID and would have minted a token for "" - a failure that looks like an outage | `SupersetProperties` |
| 2026-11-22 | 🐛 Spring's status-carrying exceptions share no base class, so naming them one at a time was whack-a-mole; the handler now asks for the ErrorResponse interface | `GlobalExceptionHandler` |
| 2026-11-22 | Superset's guest-token POST needs bearer token + CSRF token + the session cookie issued with it - exactly what Phase 6's superset_api.py predicted | `GuestTokenService` |
| 2026-11-22 | springdoc-openapi 3.2.1 chosen by checking its POM for the Boot parent it was built against (4.2.0), not assumed from the version number | pom.xml |
| 2026-11-22 | No global OpenAPI security requirement - only the watchlist operations carry one, so the published document doesn't label the public batch checker as needing an account | `OpenApiConfig` |
| 2026-11-22 | OpenApiTest asserts every published operation has a summary and a tag, so an undocumented new endpoint fails the build instead of quietly shipping a less-true API page | `OpenApiTest` |
| 2026-11-22 | **Phase 9 (Backend) complete - all 8 steps, done-when demonstrated live against the real stack** | PROGRESS.md §Phase 9 |
