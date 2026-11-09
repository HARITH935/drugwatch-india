# PROGRESS — DrugWatch India

Live checklist. Update after every step. Full plan: [DRUGWATCH_PHASES.md](DRUGWATCH_PHASES.md).

**Current phase:** Phase 2 — PDF extraction 🟨 **in progress** (approved 2026-11-08).

---

## Phase status

| Phase | Name | Status |
|---|---|---|
| 0 | Setup | ✅ Done |
| 1 | Source discovery | ✅ Done |
| 2 | PDF extraction ⚠️ checkpoint | 🟨 In progress |
| 3 | Cleaning (bronze → silver) | ⬜ Not started |
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
- [ ] 4. Attach provenance to each row: source file, page, row index.
- [ ] 5. Assign a confidence flag per row (all required fields present and well-formed = high).
- [ ] 6. Write rows to `bronze/` as Parquet.
- [ ] 7. Create a **labelled eval set**: ~300 rows labelled by hand, sampled across months and layouts.
- [ ] 8. Measure rule-based parser accuracy against the labelled eval set (field-level precision/recall/F1).

**Done when:** parser runs across the whole archive and baseline F1 is recorded.
**Checkpoint decision:** if extraction quality is too low or PDFs are mostly scanned images, re-scope here.

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
