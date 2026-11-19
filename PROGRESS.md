# PROGRESS — DrugWatch India

Live checklist. Update after every step. Full plan: [DRUGWATCH_PHASES.md](DRUGWATCH_PHASES.md).

**Current phase:** Phase 4 — Warehouse (gold). Approved 2026-11-18. Step 1 of 5 done.
**Next:** step 5 — `dbt docs` for lineage, then Phase 4's done-when check.

---

## Phase status

| Phase | Name | Status |
|---|---|---|
| 0 | Setup | ✅ Done |
| 1 | Source discovery | ✅ Done |
| 2 | PDF extraction ⚠️ checkpoint | ✅ Done |
| 3 | Cleaning (bronze → silver) | ✅ Done |
| 4 | Warehouse (gold) | 🟨 In progress |
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
- [ ] Step 5 — dbt docs for lineage

**Done when:** `dbt build` succeeds with all tests passing.

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
