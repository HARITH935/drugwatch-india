# PROGRESS — DrugWatch India

Live checklist. Update after every step. Full plan: [DRUGWATCH_PHASES.md](DRUGWATCH_PHASES.md).

**Current phase:** Phase 3 — Cleaning (bronze → silver) 🟨 **in progress** (approved 2026-11-12).

---

## Phase status

| Phase | Name | Status |
|---|---|---|
| 0 | Setup | ✅ Done |
| 1 | Source discovery | ✅ Done |
| 2 | PDF extraction ⚠️ checkpoint | ✅ Done |
| 3 | Cleaning (bronze → silver) | 🟨 In progress |
| 4 | Warehouse (gold) | ⬜ Not started |
| 5 | Automation | ⬜ Not started |
| 6 | Analytics | ⬜ Not started |
| 7 | Data science | ⬜ Not started |
| 8 | Model serving | ⬜ Not started |
| 9 | Backend | ⬜ Not started |
| 10 | LLM extraction | ⬜ Not started |
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
- [ ] 5. **Manufacturer entity resolution** with RapidFuzz: cluster spelling variants into one canonical manufacturer;
      keep a reviewed mapping table.
- [ ] 6. Map failure reasons into standard categories (Assay, Dissolution, Sterility, Description, Particulate,
      Spurious, Other).
- [ ] 7. Deduplicate repeated rows across central and state lists.
- [ ] 8. Great Expectations suite: required fields not null, valid dates, batch number format, category values in
      allowed set, row counts within expected range.
- [ ] 9. **Pandas vs PySpark benchmark:** run the same cleaning job in both on the full archive; record runtime and peak
      memory in `docs/benchmarks.md`.

**Done when:** silver data passes all GE checks, manufacturer duplicates are resolved, and the Pandas vs PySpark
benchmark is recorded.

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
