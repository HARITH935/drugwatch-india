# DrugWatch India — Detailed Project Document

> A medicine quality & price intelligence platform built on CDSCO's monthly
> "Not of Standard Quality (NSQ) / Spurious" drug alerts.

---

## Table of Contents
1. Project Overview
2. Background: What Is an NSQ Drug?
3. Target Users
4. Core Features (Detailed)
5. Data Sources
6. Mandatory Tech Stack
7. System Architecture
8. Data Model
9. Phases (Detailed, Step by Step)
10. API Design
11. Frontend Pages
12. Machine Learning Design
13. LLM Design
14. Testing Strategy
15. Security
16. Monitoring & Operations
17. Risks & Mitigations
18. Project Rules, Ethics & Legal
19. Repository Structure
20. Tool-to-Phase Map
21. Interview Talking Points
22. Resume Bullets
23. Progress Tracker
24. Glossary

---

## 1. Project Overview

**Problem:** Every month, India's drug regulator (CDSCO) tests medicine samples collected from pharmacies and distributors. Batches that fail are published as PDF lists on the CDSCO portal. These PDFs are hard to find, hard to read, and impossible to search. A patient holding a strip of tablets has no practical way to know whether that exact batch failed testing.

**Solution:** DrugWatch India automatically collects these PDFs every month, extracts the data, cleans it, stores it in a data warehouse, and turns it into a public website with:

- A **batch checker** ("Is my medicine batch flagged?")
- **Public dashboards** showing failure trends
- **Price comparisons** between branded medicines and Jan Aushadhi generics
- An **ML risk score** for manufacturers
- **Watchlist email alerts**

**One-line pitch:**
*"A website that tells you if your medicine batch failed government quality tests."*

**Why this project is strong:**
- Real, messy, monthly-updating government data (not a Kaggle CSV)
- A true end-to-end system: data engineering → analytics → ML → LLM → backend → frontend → deployment
- Clear social value and an easy story to tell
- Domain knowledge (drug names, salts, dosage forms, failure reasons) gives a real edge

---

## 2. Background: What Is an NSQ Drug?

| Term | Meaning |
|---|---|
| **NSQ (Not of Standard Quality)** | A drug sample that fails one or more quality tests (e.g. assay/potency, dissolution, sterility, description, particulate matter). |
| **Spurious drug** | A fake drug: made by an unauthorised manufacturer, often using another company's brand name. |
| **Batch** | One production lot of a medicine, identified by a batch number printed on the pack. |
| **Central labs** | CDSCO's central/regional drug testing laboratories. |
| **State labs** | State drug testing laboratories that also report failures. |

**Key point:** an NSQ finding applies to **one specific batch**, not to the whole product or company. The whole platform is designed around this.

**Typical fields in an alert row:**
- Product name (brand + generic)
- Batch number
- Manufacturing date and expiry date
- Manufacturer name and address
- Reason for failure
- Reporting lab / state
- Alert month

---

## 3. Target Users

| User | Need | What DrugWatch gives them |
|---|---|---|
| **Patients & families** | "Is my medicine safe?" | Batch checker, simple results, watchlist alerts |
| **Pharmacists** | Check stock against recent alerts | Fast batch lookup, recent alert feed |
| **Doctors** | Awareness of quality issues in commonly prescribed drugs | Drug-class dashboards, drug pages |
| **Journalists & researchers** | Trends across states and manufacturers | Public dashboards, historical data |
| **Recruiters / interviewers** | Evidence of real engineering skill | A live, working, end-to-end system |

---

## 4. Core Features (Detailed)

### 4.1 Batch Checker
- User enters medicine name and batch number (from the strip/bottle).
- System searches all historical alerts using normalized names and batch numbers.
- Result states:
  - ✅ **Not found in any alert** (with a note that this is not a safety guarantee)
  - ⚠️ **Flagged**: shows batch, alert month, failure reason, reporting lab, and a link to the original CDSCO PDF
  - 🔍 **Close matches**: similar names/batches, in case of typos

### 4.2 Public Dashboards
1. **Manufacturer view:** number of NSQ batches reported per manufacturer over time, repeat appearances
2. **State heatmap:** where failed samples were manufactured and where they were reported
3. **Drug-class view:** which drug categories (antibiotics, antidiabetics, etc.) fail most and why
4. **Price gap:** branded price vs Jan Aushadhi generic price for the same salt

Dashboards are built in Superset and embedded in the website with the Superset embedded SDK, using short-lived guest tokens issued by the Spring Boot API.

### 4.3 Manufacturer Risk Score
- ML model estimates the probability that a manufacturer appears in the NSQ list in the coming months.
- Each score comes with **SHAP explanations** ("score is high mainly because of 3 reports in the last 6 months").
- Shown with neutral wording and clear limitations.

### 4.4 Drug & Manufacturer Pages
- Drug page: all reported batches, common failure reasons, generic alternatives and prices.
- Manufacturer page: reported batches over time, drug classes, risk score with explanation.

### 4.5 Watchlist & Email Alerts
- Logged-in users add medicines (by generic or brand name) to a watchlist.
- When a new monthly alert includes a matching drug, the user gets an email.
- Emails are sent over SMTP with `spring-boot-starter-mail`: Mailpit catches them in local dev, Brevo's free SMTP delivers them in production.

### 4.6 Price Comparison
- For a given salt/composition, show NPPA ceiling price, typical branded price, and Jan Aushadhi price.

---

## 5. Data Sources

| Source | Content | Format | Frequency |
|---|---|---|---|
| **CDSCO NSQ portal** (central + state labs) — **primary from 2019** (ADR 0004) | Failed batches with product, brand, batch, dates, manufacturer, result, lab, month | JSON | Monthly (Jan 2019 →) |
| CDSCO NSQ / Spurious Drug Alerts (central labs) | Failed batches with product, batch, dates, manufacturer, failure reason | PDF | Monthly until Jun 2025 (patchy) |
| CDSCO State Drug Alerts (state labs) | Same structure, from state labs | PDF | Monthly until Jun 2025 (patchy) |
| NPPA ceiling price lists | Government price caps for scheduled medicines | PDF; CSV via manual download (ADR 0003) | Periodic |
| Jan Aushadhi product list | Generic medicine names and MRPs | JSON (public API) | Periodic |

> Exact URLs, formats, layout changes over time, and quirks are confirmed and documented in **Phase 1** (`docs/data-sources.md`).
> Access and republishing rules: ADR 0003. CDSCO and Jan Aushadhi data needs written permission before it is
> published on the live site (`docs/permissions.md`).

**Expected data challenges:**
- Table layouts change between months and between central/state lists
- Rows split across pages; merged cells; multi-line product names
- Inconsistent manufacturer spellings ("Ltd", "Ltd.", "Limited", typos)
- Dates in several formats; missing fields
- Some PDFs may be scanned images rather than text

---

## 6. Mandatory Tech Stack

Every tool below **must** be used. No substitutions or removals without approval.

| Layer | Tools | Purpose |
|---|---|---|
| Languages | Python, Java, SQL, TypeScript | Pipelines/ML, backend, warehouse, frontend |
| Ingestion & orchestration | Airflow | Monthly scheduled pipeline + backfill |
| PDF extraction | pdfplumber, Camelot | Rule-based table extraction |
| Data lake | RustFS | S3-compatible storage for raw/bronze/silver Parquet |
| Processing | Apache Spark (PySpark) | Cleaning and normalization at scale |
| Transformation | dbt | Builds the gold layer (marts) in Postgres + tests |
| Data quality | Great Expectations | Automated data validation |
| Warehouse / DB | PostgreSQL | Gold layer (dbt marts) + application database |
| Analytics | Apache Superset, Pandas | Dashboards, exploration, Pandas-vs-Spark benchmark |
| Data science | LightGBM, SHAP, RapidFuzz, MLflow | Risk model, explanations, fuzzy matching, tracking |
| Model serving | ONNX, onnxmltools, ONNX Runtime, FastAPI | LightGBM → ONNX conversion, fast inference service |
| LLM | Hugging Face Transformers, PEFT (LoRA) | Fine-tuned field extraction |
| Backend | Spring Boot, Spring Security + JWT, Spring Data JPA, Flyway, Redis, spring-boot-starter-mail, Testcontainers + JUnit, OpenAPI | Main application API, Superset guest tokens, watchlist emails |
| Email | Mailpit (local dev), Brevo free SMTP (production) | Watchlist emails + Airflow failure alerts |
| Frontend | Next.js, Tailwind CSS, Superset embedded SDK (`@superset-ui/embedded-sdk`) | Public website with embedded dashboards |
| DevOps | Docker, Docker Compose, GitHub Actions, Cloud VM, Nginx / Caddy | Containers, CI/CD, HTTPS hosting |

### 6.1 Approved Additions

Approved 2026-11-03. Rationale is recorded in `docs/adr/0001-stack-choice.md` and `docs/adr/0002-rustfs-replaces-minio.md`.

| Addition | Why | Phase |
|---|---|---|
| `@superset-ui/embedded-sdk` + Superset guest-token API | Embed Superset dashboards in the Next.js site | 9 (guest-token endpoint), 11 (embedding) |
| `spring-boot-starter-mail` | Send watchlist emails from Spring Boot | 9 |
| Mailpit | Local SMTP server + web inbox that catches all mail in dev | 0 |
| Brevo free SMTP | Production email delivery (watchlist + Airflow alerts) | 12 |
| onnxmltools | Convert the LightGBM model to ONNX | 8 |
| RustFS (replaces MinIO) | MinIO's community edition was discontinued (no Docker images, repo unmaintained); RustFS is an S3-compatible drop-in. See ADR 0002 | 0 |

Email credentials (and every other secret) come only from environment variables.

---

## 7. System Architecture

```
            ┌──────────────────────────────────────────────┐
            │  CDSCO / NPPA / Jan Aushadhi public sources   │
            └──────────────────────┬───────────────────────┘
                                   │  (polite, rate-limited download)
                                   ▼
                     ┌───────────────────────────┐
                     │  Airflow monthly DAG       │
                     └─────────────┬─────────────┘
                                   ▼
                     RustFS raw/      (original PDFs, never modified)
                                   │
                                   ▼
               pdfplumber + Camelot rule-based parser
                     │                         │
          parsed rows│                         │ failed / low-confidence rows
                     ▼                         ▼
             RustFS bronze/        LoRA fine-tuned LLM extractor
               (Parquet)  ◄────────────────────┘
                     │
                     ▼
     PySpark cleaning + RapidFuzz entity resolution
         + Great Expectations validation
                     │
                     ▼
             RustFS silver/ (clean Parquet)
                     │
                     ▼
     PostgreSQL  ◄── dbt: staging → intermediate → marts (= gold)
          │                 │                         │
          ▼                 ▼                         ▼
   Superset dashboards   LightGBM + SHAP        Spring Boot API
          │              (MLflow tracking)      (JWT, JPA, Flyway, Redis,
          │                   │                  guest tokens, email)
          │                   ▼                       │
          │          ONNX → FastAPI + ONNX  ◄─────────┤ (risk-score proxy)
          │                Runtime                    │
          │                                           ▼
          └──── embedded SDK ────►        Next.js + Tailwind website
                                                      │
                                                      ▼
                  Docker + GitHub Actions + Cloud VM + Nginx/Caddy (HTTPS)
```

**Email path:** Spring Boot (watchlist emails) and Airflow (failure alerts) both send over SMTP: Mailpit in local dev, Brevo in production. Credentials come only from environment variables.

**Embedding path:** the browser asks Spring Boot for a short-lived Superset guest token, then the embedded SDK loads the dashboard from Superset with that token.

**Data layers (medallion pattern): raw → bronze → silver → gold**

| Layer | Where | Contents | Rule |
|---|---|---|---|
| `raw/` | RustFS | Original PDFs/Excels exactly as downloaded | Never modified; source of truth |
| `bronze/` | RustFS | Parsed rows as extracted, with source file + page + row reference | Minimal changes |
| `silver/` | RustFS | Cleaned, standardized, deduplicated rows (Parquet) | Passed all quality checks |
| gold | PostgreSQL | dbt marts: star schema (Section 8.1) + `mart_*` tables (Section 8.2) | Built and tested by dbt; what Superset, the ML pipeline and the API read |

RustFS has three buckets (`raw`, `bronze`, `silver`); gold lives in Postgres. dbt's `staging` and `intermediate` models are internal build steps on the way to gold, not a separate layer.

---

## 8. Data Model

### 8.1 Gold Layer: Star Schema (dbt marts)

**`fact_nsq_sample`** — one row per failed batch report

| Column | Type | Notes |
|---|---|---|
| sample_id | PK | Surrogate key |
| drug_id | FK → dim_drug | |
| manufacturer_id | FK → dim_manufacturer | |
| reported_state_id | FK → dim_state | Reporting lab state |
| alert_date_id | FK → dim_date | Alert month |
| batch_no | text | Normalized batch number |
| batch_no_raw | text | As printed in source |
| mfg_date | date | |
| expiry_date | date | |
| failure_reason_raw | text | Original text |
| failure_category | text | e.g. Assay, Dissolution, Sterility, Description, Spurious |
| lab_type | text | Central / State |
| is_spurious | boolean | |
| source_file | text | PDF name in RustFS |
| source_page | int | Page number |
| source_url | text | Link to original document |
| extraction_method | text | rule / llm |

**`fact_price`** — one row per drug price record

| Column | Notes |
|---|---|
| price_id | PK |
| drug_id | FK |
| price_source | NPPA / Jan Aushadhi |
| pack_size | |
| price | |
| effective_date_id | FK → dim_date |

**`dim_drug`**

| Column | Notes |
|---|---|
| drug_id | PK |
| brand_name | |
| generic_name | Normalized salt/composition |
| strength | e.g. 500 mg |
| dosage_form | Tablet, Capsule, Syrup, Injection… |
| drug_class | Antibiotic, Antidiabetic, Antihypertensive… |

**`dim_manufacturer`**

| Column | Notes |
|---|---|
| manufacturer_id | PK |
| canonical_name | After entity resolution |
| name_variants | All raw spellings matched to this entity |
| state | Manufacturing state |
| city | |

**`dim_state`**, **`dim_date`**: standard dimension tables.

### 8.2 Gold Layer: Analytical Marts (examples)

| Mart | What it answers | SQL techniques |
|---|---|---|
| `mart_manufacturer_trend` | NSQ batches per manufacturer per month, rolling 6/12-month counts | Window functions (`SUM() OVER`), CTEs |
| `mart_repeat_offenders` | Manufacturers appearing in 3+ separate alert months | `DENSE_RANK`, `LAG` |
| `mart_state_summary` | Reports by manufacturing and reporting state | Aggregations, CTEs |
| `mart_drug_class_failures` | Failure categories per drug class over time | Pivot-style aggregation |
| `mart_price_gap` | Branded vs generic price per salt | Joins across facts, percent difference |
| `mart_ml_features` | Feature table for the risk model | Time-windowed aggregates |

### 8.3 Application Tables (Spring Boot, Flyway-managed)

| Table | Purpose |
|---|---|
| `users` | Accounts (email, password hash, role) |
| `watchlist_items` | User → drug watch entries |
| `alert_notifications` | Emails sent (user, drug, alert month, sent time) |
| `refresh_tokens` | JWT refresh token store |

---

## 9. Phases (Detailed, Step by Step)

### Stage A — Get the Data

#### Phase 0 — Setup
**Goal:** A clean repo with base services running.

**Steps:**
1. Create monorepo structure (see Section 19).
2. Write `CLAUDE.md`, `PROGRESS.md`, `README.md`, `docs/adr/0001-stack-choice.md`.
3. Create `docker-compose.yml` with PostgreSQL, RustFS, Redis, and Mailpit (local SMTP server + web inbox for testing emails).
4. Add `.env.example` (no real secrets committed), including SMTP settings pointing at Mailpit.
5. Add GitHub Actions workflow for linting (Python + Java + TypeScript as each appears).
6. Create RustFS buckets: `raw`, `bronze`, `silver` (gold lives in Postgres, not RustFS).

**Deliverables:** planning files, compose file, CI lint workflow.
**Done when:** `docker compose up` starts all four services; RustFS buckets exist; the Mailpit inbox is reachable; CI passes.

---

#### Phase 1 — Source Discovery
**Goal:** Know exactly where the data is and download all of it.

**Steps:**
1. Locate CDSCO central and state alert pages; record URL patterns.
2. Locate NPPA and Jan Aushadhi lists.
3. Check `robots.txt` and terms for each source.
4. Build a downloader: rate-limited, retries, skips files already in RustFS (hash check).
5. Download the full historical archive into `raw/` with metadata (source, alert month, download time, file hash).
6. Document everything in `docs/data-sources.md`: URLs, formats, layout changes over time, scanned vs text PDFs.

**Deliverables:** downloader module, full raw archive, data-source documentation.
**Done when:** every available historical file is in RustFS with metadata, and sources are documented.

---

#### Phase 2 — PDF Extraction ⚠️ Key Checkpoint
**Goal:** Turn PDFs into structured rows.

**Steps:**
1. Classify PDFs: text-based vs scanned; layout family (central vs state, old vs new format).
2. Build pdfplumber extraction for each layout family; use Camelot where table borders are clear.
3. Handle multi-page tables, merged cells, and multi-line product names.
4. Attach provenance to each row: source file, page, row index.
5. Assign a confidence flag per row (all required fields present and well-formed = high).
6. Write rows to `bronze/` as Parquet.
7. Create a **labelled eval set**: ~300 rows labelled by hand, sampled across months and layouts.
8. Measure rule-based parser accuracy against the labelled eval set (field-level precision/recall/F1).

**Deliverables:** parser, bronze Parquet, extraction report, labelled eval set, baseline F1.
**Done when:** parser runs across the whole archive and baseline F1 is recorded.
**Checkpoint decision:** if extraction quality is too low or PDFs are mostly scanned images, re-scope here (e.g. limit to recent years or one source type) before moving on.

---

### Stage B — Build the Data Platform

#### Phase 3 — Cleaning (Bronze → Silver)
**Goal:** Consistent, trustworthy data.

**Steps:**
1. PySpark job reads bronze Parquet.
2. Normalize text: case, whitespace, punctuation, common abbreviations ("Ltd." → "Limited").
3. Parse dates from all observed formats; validate mfg date < expiry date.
4. Split product name into brand, generic/salt, strength, dosage form.
5. **Manufacturer entity resolution** with RapidFuzz: cluster spelling variants into one canonical manufacturer; keep a reviewed mapping table.
6. Map failure reasons into standard categories (Assay, Dissolution, Sterility, Description, Particulate, Spurious, Other).
7. Deduplicate repeated rows across central and state lists.
8. Great Expectations suite: required fields not null, valid dates, batch number format, category values in allowed set, row counts within expected range.
9. **Pandas vs PySpark benchmark:** run the same cleaning job in both on the full archive; record runtime and peak memory in `docs/benchmarks.md`.

**Deliverables:** Spark jobs, mapping tables, GE suite, silver Parquet, `docs/benchmarks.md`.
**Done when:** silver data passes all GE checks, manufacturer duplicates are resolved, and the Pandas vs PySpark benchmark is recorded.

---

#### Phase 4 — Warehouse
**Goal:** Analytics-ready data in Postgres (the gold layer).

**Steps:**
1. Load silver data into Postgres staging schema.
2. Build dbt project: `staging` (type casting, renaming) → `intermediate` (joins, enrichment) → `marts` (business tables = **gold layer**).
3. Build the star schema (Section 8.1) and marts (Section 8.2).
4. Add dbt tests: unique, not_null, relationships, accepted_values, plus custom tests (e.g. expiry after mfg).
5. Generate dbt docs for lineage.

**Deliverables:** dbt project, star schema, marts, dbt docs.
**Done when:** `dbt build` succeeds with all tests passing.

---

#### Phase 5 — Automation
**Goal:** The pipeline runs itself every month.

**Steps:**
1. Monthly DAG: check for new alerts → download → extract → (LLM fallback, once Phase 10 exists) → Spark clean → GE validate → dbt build → trigger watchlist alerts.
2. Backfill DAG: reprocess any historical range.
3. Retries with backoff; idempotent tasks (safe to re-run).
4. Failure notifications by email over SMTP (Mailpit locally, Brevo in production; credentials via env vars only).
5. Run log: files processed, rows added, checks passed/failed.

**Deliverables:** two DAGs, alerting, run logs.
**Done when:** both DAGs run end-to-end with no manual steps and re-runs don't create duplicates.

---

### Stage C — Insights & Intelligence

#### Phase 6 — Analytics
**Goal:** Public, read-only dashboards.

**Steps:**
1. Pandas exploration notebook: distributions, top manufacturers, failure categories, seasonality, data gaps.
2. Connect Superset to the gold marts.
3. Build four dashboards: manufacturer trends, state heatmap, drug-class failures, price gap.
4. Configure public read-only access.
5. Add the disclaimer and source notes on every dashboard.

**Deliverables:** notebook, four dashboards.
**Done when:** dashboards are viewable publicly with filters working.

---

#### Phase 7 — Data Science
**Goal:** Manufacturer risk score with explanations.

**Steps:**
1. Define the label (see Section 12).
2. Build features from `mart_ml_features`.
3. Time-based split (train on earlier periods, test on later); no leakage.
4. Baselines: "predict last period's status" and logistic regression.
5. Train LightGBM; tune key hyperparameters.
6. Evaluate: AUC, PR-AUC, precision at top-K.
7. SHAP: global feature importance + per-manufacturer explanations.
8. Track all runs and register the best model in MLflow.

**Deliverables:** training pipeline, evaluation report, SHAP outputs, registered model.
**Done when:** LightGBM beats both baselines on the time-based test set, and explanations are generated.

---

#### Phase 8 — Model Serving
**Goal:** Fast, portable predictions.

**Steps:**
1. Export the LightGBM model to ONNX with onnxmltools.
2. Verify ONNX predictions match the original model.
3. Build FastAPI service: `/predict`, `/explain`, `/health`.
4. Containerize; load model version from MLflow.
5. Benchmark latency (p50/p95) under load.

**Deliverables:** ONNX model, FastAPI service, benchmark report.
**Done when:** service runs in Docker, outputs match the original model, latency recorded.

> Note: onnxmltools (the LightGBM → ONNX converter) was approved for this phase on 2026-11-03 (see Section 6.1).

---

### Stage D — Product

#### Phase 9 — Backend
**Goal:** The main application API.

**Steps:**
1. Spring Boot project with layered structure (controller → service → repository).
2. Flyway migrations for app tables (Section 8.3).
3. Spring Data JPA entities for warehouse read models + app tables.
4. Endpoints (Section 10).
5. Spring Security: registration, login, JWT access token + refresh token, role-based access.
6. Redis caching for batch lookups and drug/manufacturer pages.
7. Risk-score proxy to the FastAPI service with timeouts and graceful fallback.
8. **Superset guest-token endpoint:** enable embedding in Superset (`EMBEDDED_SUPERSET` feature flag, read-only guest role); Spring Boot calls the Superset API with a service account (credentials from env vars) and returns short-lived guest tokens for allowlisted dashboards only.
9. Watchlist + email notifications with `spring-boot-starter-mail` (triggered after each monthly pipeline run); Mailpit locally, Brevo in production.
10. Global error handling, validation, rate limiting on public lookup and the guest-token endpoint.
11. Tests: unit (JUnit), integration (Testcontainers with real Postgres + Redis), email delivery checked in Mailpit.
12. OpenAPI / Swagger documentation.

**Deliverables:** working API, guest-token endpoint, email notifications, tests, Swagger docs.
**Done when:** all endpoints work, the guest-token endpoint returns a valid Superset token, watchlist emails arrive in Mailpit, test suite passes in CI, Swagger docs are live.

---

#### Phase 10 — LLM Extraction
**Goal:** Recover rows the rule-based parser can't handle.

**Steps:**
1. Collect training data: rows where parser output was verified/corrected, plus the labelled eval set split into train/validation/test (keeping the test split untouched).
2. Choose a small open model that fits free/cheap GPU (see Section 13).
3. Fine-tune with LoRA (PEFT) to output strict JSON fields.
4. Evaluate field-level F1 on the labelled eval set's test split vs the rule-based baseline.
5. Integrate as a fallback for low-confidence rows; validate JSON output before accepting.
6. Mark extracted rows with `extraction_method = llm`.

**Deliverables:** fine-tuned adapter, evaluation report, pipeline integration.
**Done when:** the LLM beats the rule-based baseline on labelled-eval-set F1 for low-confidence rows.

---

#### Phase 11 — Frontend
**Goal:** The public website.

**Steps:**
1. Next.js app with Tailwind.
2. Build pages (Section 11).
3. Auth flow (login, register, token refresh).
4. Embed Superset dashboards with `@superset-ui/embedded-sdk`, using guest tokens from the Phase 9 endpoint (refreshed before they expire).
5. Responsive design (most users will be on phones).
6. Disclaimer and source links on every result.

**Deliverables:** complete website.
**Done when:** all pages work against the live backend on desktop and mobile.

---

### Stage E — Launch

#### Phase 12 — Deploy & Harden
**Goal:** A live, reliable public system.

**Steps:**
1. Production Docker images for every service.
2. GitHub Actions CI/CD: lint → test → build images → deploy to cloud VM on push to main.
3. Nginx or Caddy reverse proxy with HTTPS.
4. Environment secrets managed outside the repo (database, JWT keys, Brevo SMTP, Superset service account).
5. Switch SMTP from Mailpit to Brevo; verify a watchlist email and an Airflow failure email are delivered.
6. Database and RustFS backups.
7. Health checks, logs, and uptime monitoring.
8. Final documentation, demo video, and public launch.

**Deliverables:** live site, CI/CD, production email, backups, monitoring.
**Done when:** the site is live over HTTPS, auto-deploys on push, production emails are delivered via Brevo, and backups run.

---

## 10. API Design (Spring Boot)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/batches/search?drug=&batch=` | Public (rate-limited) | Batch checker |
| GET | `/api/v1/drugs/{id}` | Public | Drug details + reported batches |
| GET | `/api/v1/drugs/search?q=` | Public | Drug search with fuzzy matching |
| GET | `/api/v1/manufacturers/{id}` | Public | Manufacturer page data |
| GET | `/api/v1/manufacturers/{id}/risk` | Public | Risk score + SHAP explanation (proxied to FastAPI) |
| GET | `/api/v1/alerts/latest` | Public | Most recent alert month summary |
| GET | `/api/v1/prices/compare?salt=` | Public | Branded vs generic price comparison |
| POST | `/api/v1/dashboards/{key}/guest-token` | Public (rate-limited) | Short-lived Superset guest token for an allowlisted dashboard |
| POST | `/api/v1/auth/register` | Public | Create account |
| POST | `/api/v1/auth/login` | Public | Get JWT tokens |
| POST | `/api/v1/auth/refresh` | Public | Refresh access token |
| GET | `/api/v1/watchlist` | User | List watchlist |
| POST | `/api/v1/watchlist` | User | Add drug to watchlist |
| DELETE | `/api/v1/watchlist/{id}` | User | Remove from watchlist |

**FastAPI (internal):** `/predict`, `/explain`, `/health`

---

## 11. Frontend Pages (Next.js)

| Page | Contents |
|---|---|
| **Home** | Batch checker search box, latest alert summary, project explanation |
| **Batch result** | Flagged / not found / close matches, with source link and disclaimer |
| **Drug page** | Reported batches, failure reasons, generic alternatives, prices |
| **Manufacturer page** | Reported batches over time, drug classes, risk score + explanation |
| **Dashboards** | Embedded Superset dashboards |
| **Price compare** | Salt search → branded vs generic prices |
| **Login / Register** | Auth forms |
| **Watchlist** | Manage watched drugs, notification history |
| **About & Methodology** | Data sources, how extraction and risk scoring work, limitations |

---

## 12. Machine Learning Design

**Task:** Binary classification at the manufacturer level.

**Label:** Does this manufacturer appear in at least one NSQ alert in the **next N months** (e.g. N = 6) after a cutoff date?

**Features (computed only from data before the cutoff):**
- Number of NSQ reports in last 3 / 6 / 12 / 24 months
- Months since last report
- Number of distinct drugs reported
- Share of reports by failure category (assay, dissolution, sterility…)
- Share of reports by drug class
- Number of distinct reporting states
- Central vs state lab report ratio
- Any spurious-drug association
- Trend features (increase/decrease in reports)

**Validation:** rolling time-based splits (train on earlier cutoffs, test on later ones). No random splits.

**Baselines:**
1. "Reported in the last N months → will be reported again"
2. Logistic regression

**Metrics:** ROC-AUC, PR-AUC, precision@top-K.

**Explainability:** SHAP global importance + per-manufacturer top contributing features.

**Known limitation (must be stated publicly):** the model only sees *reported* failures. Sampling is not random, so the score reflects reporting history, not true quality.

---

## 13. LLM Design

**Task:** Convert a messy text row (or row block) from a PDF into strict JSON:

```json
{
  "product_name": "...",
  "generic_name": "...",
  "batch_no": "...",
  "mfg_date": "YYYY-MM",
  "expiry_date": "YYYY-MM",
  "manufacturer": "...",
  "failure_reason": "..."
}
```

**Model:** a small open instruction-tuned model (around 0.5B–3B parameters) that can be fine-tuned on a free or low-cost GPU.

**Method:** LoRA via PEFT (optionally QLoRA to save memory).

**Training data:** verified parser outputs + corrected rows + labelled eval set train split.

**Evaluation:** field-level precision/recall/F1 on the untouched test split of the labelled eval set, compared against the rule-based parser.

**Safety in pipeline:**
- JSON schema validation before accepting output
- Reject outputs with invented fields or impossible dates
- Mark all LLM-extracted rows for traceability

---

## 14. Testing Strategy

| Layer | Tests |
|---|---|
| Extraction | Unit tests on sample PDFs per layout family; regression tests against the labelled eval set |
| Spark | Unit tests for normalization functions; small-data job tests; Pandas vs PySpark benchmark (`docs/benchmarks.md`) |
| Data quality | Great Expectations suites on every run |
| Warehouse | dbt tests (unique, not_null, relationships, accepted_values, custom) |
| ML | Leakage checks, metric thresholds, ONNX vs original prediction parity |
| FastAPI | Endpoint tests, latency benchmark |
| Backend | JUnit unit tests, Testcontainers integration tests, auth tests (valid/expired/wrong-role tokens), guest-token tests (allowlist, rate limit), email delivery checked in Mailpit |
| Frontend | Component tests for key pages, basic end-to-end flow (search → result) |
| CI | All tests run on every push |

---

## 15. Security

- Passwords hashed (BCrypt via Spring Security).
- Short-lived JWT access tokens + refresh tokens.
- Secrets in environment variables; `.env` never committed.
- Rate limiting on public endpoints.
- Input validation on all endpoints.
- CORS restricted to the frontend domain.
- HTTPS everywhere.
- Internal services (Postgres, RustFS, Redis, FastAPI) not exposed publicly.
- SMTP (Mailpit/Brevo) and Superset service-account credentials only in environment variables.
- Superset is reachable only through the reverse proxy (the embedded dashboards need it); guest tokens are short-lived, use a read-only guest role, and cover allowlisted dashboards only.

---

## 16. Monitoring & Operations

- Health endpoints for every service.
- Centralized logs per container.
- Airflow run history + failure emails (SMTP: Mailpit locally, Brevo in production).
- Pipeline metrics: files processed, rows added, GE failures, LLM fallback rate.
- Uptime monitoring for the public site.
- Scheduled backups of Postgres and RustFS.

---

## 17. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| PDF layouts change | Parser breaks | Layout-family parsers, GE row-count checks, LLM fallback |
| Scanned (image) PDFs | Text extraction fails | Detect early in Phase 2; scope decision at checkpoint |
| Portal blocks or changes URLs | Ingestion fails | Cached raw archive, rate limiting, alerts on failure |
| Manufacturer name ambiguity | Wrong attribution | Reviewed mapping table, conservative fuzzy thresholds |
| Defamation concerns | Legal/ethical risk | Batch-level wording, source links, neutral language, disclaimers |
| ML misinterpreted as "quality rating" | Misleading users | Clear methodology page and limitations |
| Too many new tools | Slow progress | One phase at a time; finish each phase before starting the next |
| Small dataset for ML | Weak model | Strong baselines, honest reporting, focus on explainability |

---

## 18. Project Rules, Ethics & Legal

### Working Rules
- **Phases only**: no day, week, or month timelines.
- **One phase at a time**: the next phase starts only after approval.
- **Stack is locked**: any library outside the mandatory stack needs approval first. Approved additions are listed in Section 6.1 and recorded in `docs/adr/`.
- **Every phase** has deliverables, acceptance criteria, and tests.
- **Must be deployed** as a live public project.

### Ethics & Legal
- An NSQ finding applies to **one specific batch**, not the whole product or company.
- Every view shows the **batch number**, **source alert month**, and **link to the original CDSCO document**.
- Disclaimer on every page: *"Not medical advice. Data from CDSCO public alerts."*
- Neutral wording only ("number of NSQ batches reported"). Never call a manufacturer fraudulent.
- "Not found" never means "guaranteed safe".

### Scraping Etiquette
- Respect `robots.txt` and site terms.
- Rate-limit all requests.
- Cache raw files in RustFS so sources are never re-downloaded unnecessarily.

---

## 19. Repository Structure

```
drugwatch-india/
├── ingestion/        # Downloaders, Airflow DAGs
├── extraction/       # pdfplumber + Camelot parsers, labelled eval set tools
├── spark/            # PySpark cleaning jobs
├── dbt/              # dbt project (staging, intermediate, marts)
├── quality/          # Great Expectations suites
├── ml/               # Feature prep, LightGBM training, SHAP, MLflow
├── ml-serving/       # FastAPI + ONNX Runtime service
├── llm/              # Hugging Face + PEFT LoRA fine-tuning and inference
├── backend/          # Spring Boot application
├── frontend/         # Next.js + Tailwind website
├── infra/            # Docker, compose files, Nginx/Caddy, deploy scripts
├── docs/
│   ├── adr/          # Architecture decision records
│   ├── data-sources.md
│   ├── benchmarks.md     # Pandas vs PySpark (Phase 3)
│   └── methodology.md
├── CLAUDE.md
├── DRUGWATCH_PHASES.md   # this plan
├── PROGRESS.md
└── README.md
```

---

## 20. Tool-to-Phase Map

| Tool | First used in |
|---|---|
| Docker, Docker Compose, PostgreSQL, RustFS, Redis, Mailpit, GitHub Actions | Phase 0 |
| Python | Phase 1 |
| pdfplumber, Camelot, Pandas | Phase 2 |
| PySpark, RapidFuzz, Great Expectations (+ Pandas vs PySpark benchmark) | Phase 3 |
| dbt, advanced SQL (gold layer) | Phase 4 |
| Airflow, SMTP email alerts (via Mailpit) | Phase 5 |
| Apache Superset | Phase 6 |
| LightGBM, SHAP, MLflow | Phase 7 |
| ONNX, onnxmltools, ONNX Runtime, FastAPI | Phase 8 |
| Java, Spring Boot, Spring Security + JWT, Spring Data JPA, Flyway, spring-boot-starter-mail, Superset guest-token API, Testcontainers + JUnit, OpenAPI | Phase 9 |
| Hugging Face Transformers, PEFT (LoRA) | Phase 10 |
| TypeScript, Next.js, Tailwind CSS, `@superset-ui/embedded-sdk` | Phase 11 |
| Cloud VM, Nginx / Caddy, Brevo SMTP | Phase 12 |

---

## 21. Interview Talking Points

1. **Why medallion layers (raw/bronze/silver/gold)?** Raw files are never modified, so any bug can be fixed by reprocessing from source. Gold (dbt marts in Postgres) is the only tested, business-ready layer that dashboards, ML and the API read.
2. **How did you handle messy manufacturer names?** RapidFuzz clustering + a reviewed mapping table, with conservative thresholds to avoid wrong merges.
3. **How did you prevent ML data leakage?** Features use only data before each cutoff; time-based splits, never random.
4. **Why ONNX?** Portable, fast inference independent of the training environment; verified prediction parity.
5. **Why an LLM only as a fallback?** Rule-based parsing is cheap and predictable; the LLM handles only hard rows, with schema validation and traceability.
6. **How did you measure extraction quality?** A labelled eval set (~300 rows labelled by hand) scored with field-level F1, comparing rule-based vs LLM.
7. **How did you handle the ethics of naming companies?** Batch-level facts only, source links, neutral wording, clear disclaimers and methodology.
8. **Why Spring Boot + FastAPI together?** Spring Boot for the robust main API and auth; FastAPI for Python-native ML serving.
9. **Why Spark for a dataset this small?** Spark is overkill at current volume (measured: Pandas vs PySpark runtime and memory in `docs/benchmarks.md`); chosen for full-history reprocessing, future sources, and learning.

---

## 22. Resume Bullets (fill in real numbers)

- Built an end-to-end data platform processing **[N] CDSCO drug alert PDFs** into **[N] structured records** using Airflow, PySpark, dbt, and Great Expectations.
- Fine-tuned a small LLM with LoRA for structured extraction from government PDFs, reaching **[X] field-level F1** vs **[Y]** for the rule-based baseline.
- Developed a LightGBM manufacturer risk model (**AUC [X]**) with SHAP explanations, served via ONNX Runtime at **[X] ms p95**.
- Built a Spring Boot API with JWT auth and Redis caching (**[X]% cache hit ratio**, **[X] ms p95**), tested with Testcontainers.
- Launched a public Next.js site with batch lookup, Superset dashboards, and watchlist email alerts.

---

## 23. Progress Tracker

Live status is tracked in `PROGRESS.md`; this table is the starting snapshot.

| Phase | Name | Status |
|---|---|---|
| 0 | Setup | ⬜ Not started |
| 1 | Source discovery | ⬜ Not started |
| 2 | PDF extraction ⚠️ | ⬜ Not started |
| 3 | Cleaning | ⬜ Not started |
| 4 | Warehouse | ⬜ Not started |
| 5 | Automation | ⬜ Not started |
| 6 | Analytics | ⬜ Not started |
| 7 | Data science | ⬜ Not started |
| 8 | Model serving | ⬜ Not started |
| 9 | Backend | ⬜ Not started |
| 10 | LLM extraction | ⬜ Not started |
| 11 | Frontend | ⬜ Not started |
| 12 | Deploy & harden | ⬜ Not started |

---

## 24. Glossary

| Term | Meaning |
|---|---|
| CDSCO | Central Drugs Standard Control Organisation, India's national drug regulator |
| NSQ | Not of Standard Quality: failed one or more quality tests |
| NPPA | National Pharmaceutical Pricing Authority: sets medicine price caps |
| Jan Aushadhi | Government scheme selling low-cost generic medicines |
| Medallion architecture | Raw → bronze → silver → gold data layering. Here raw, bronze and silver are RustFS buckets; gold is the dbt marts in Postgres |
| Gold layer | Business-ready, tested tables built by dbt in Postgres (star schema + `mart_*` tables) |
| Guest token | Short-lived Superset token that lets the website show an embedded dashboard without a Superset login |
| SMTP | Standard protocol for sending email |
| Mailpit | Local fake email server that catches all outgoing mail and shows it in a web inbox |
| Brevo | Email delivery service; its free SMTP tier is used in production |
| RustFS | Open-source, S3-compatible object storage (replaced MinIO, see ADR 0002) |
| Path-style addressing | S3 URLs shaped `host/bucket/key` instead of `bucket.host/key`; RustFS needs it by default |
| Star schema | Fact tables surrounded by dimension tables for analytics |
| Entity resolution | Matching different spellings to the same real-world entity |
| LoRA | Low-Rank Adaptation: efficient fine-tuning that trains small adapter weights |
| ONNX | Open Neural Network Exchange: portable model format |
| SHAP | Method to explain each feature's contribution to a prediction |
| Labelled eval set | ~300 hand-labelled PDF rows used to measure extraction accuracy (Phases 2 and 10) |
