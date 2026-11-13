# CLAUDE.md — DrugWatch India

> Persistent instructions for Claude Code. Read this file at the start of every session.
> The full plan (architecture, data model, phases, API, ML and LLM design) is in `DRUGWATCH_PHASES.md`
> and is the source of truth. Read the relevant section before starting a task. Do not re-design
> anything the plan already specifies.

---

## 1. Project in one paragraph
DrugWatch India is a public medicine quality and price intelligence platform built on CDSCO's monthly
"Not of Standard Quality (NSQ) / Spurious" drug alerts: the CDSCO NSQ portal's JSON (primary from 2019,
ADR 0004) plus the older alert PDFs. A monthly Airflow pipeline downloads both and extracts PDF rows with
pdfplumber/Camelot, using a LoRA fine-tuned LLM as a fallback for hard rows.
PySpark cleans the rows and resolves manufacturer names, Great Expectations validates them, and dbt
builds a gold layer of marts in PostgreSQL. On top of that sit Superset dashboards (embedded in the site),
a LightGBM manufacturer risk score with SHAP explanations (served with ONNX Runtime + FastAPI), a Spring
Boot API, and a Next.js website. Its main feature is the batch checker: *"Is my medicine batch flagged?"*

---

## 2. Who you are working with (READ FIRST)
- The developer (Harith) is a **beginner** in Java, Spring Boot, Docker and DevOps, and is comfortable
  with Python. Some React/TypeScript, Flask, scikit-learn, SHAP and RAG experience.
- Treat the data-platform tools (Airflow, RustFS, PySpark, dbt, Great Expectations, Superset, MLflow, ONNX,
  PEFT) as new unless Harith says otherwise.
- This is a **learning project and a placement portfolio piece**. Harith must be able to explain every
  line in an interview.

### Teaching mode (mandatory)
1. **Before each step**, say in plain English what we're doing and why.
2. **Before each new tool or concept**, give a 3–5 line plain-English intro: what it is, and why we need it here.
3. **After coding**, explain each new file in 2–4 lines and list any new terms with one-line definitions.
4. End every step with: **What we did → How to verify → What's next (one step)**.
5. Add short, meaningful comments on non-obvious lines (config keys, compose fields, annotations). No noise comments.
6. When Harith asks "why", answer with the trade-off, not just the fact.

### Pace
- **One step at a time.** Do the smallest useful slice, verify it, then **stop and wait for Harith's OK**
  before starting the next step.
- Never build a whole phase in one go, and never jump ahead to a later phase. If something from a later
  phase is needed, say so and ask.

---

## 3. Session workflow
1. Read `PROGRESS.md` and find the current phase and the next unchecked step.
2. Read that phase in `DRUGWATCH_PHASES.md` §9, plus any section it references.
3. Say in plain English what this step does and why, before writing code.
4. Implement → run tests → check against the phase's **Done when** criteria and show the output.
5. Update `PROGRESS.md`, then **stop and wait for Harith's OK**.

---

## 4. Working rules
- **Phases only.** No day, week, or month timelines anywhere.
- **One phase at a time.** The next phase starts only after the developer approves it. Never build ahead.
- **Stack is locked.** Use only the tools in `DRUGWATCH_PHASES.md` §6, including the approved additions
  in §6.1. Any other library, tool or service needs approval first. Record each approved change as an ADR
  in `docs/adr/NNNN-title.md`.
- **Every phase** has deliverables, acceptance criteria (**Done when**) and tests. A phase is done only
  when every criterion has been demonstrated.
- **Secrets:** never commit `.env`, keys or passwords; keep `.env.example` current. All credentials
  (database, JWT keys, SMTP, Superset service account) come from environment variables.
- **Must be deployed** as a live public project (Phase 12).

---

## 5. Data rules
- **Layers:** raw → bronze → silver (RustFS buckets) → gold (dbt marts in PostgreSQL).
  Superset, the ML pipeline and the API read **gold** only.
- `raw/` is **never modified**. Any fix means reprocessing from raw.
- Every row keeps provenance: source file, page, row index, source URL, and `extraction_method` (`rule` / `llm`).
- Manufacturer entity resolution uses conservative RapidFuzz thresholds plus a reviewed mapping table.
  A missed merge is better than a wrong merge.
- **ML:** features use only data from before the cutoff. Time-based splits only, never random.
- **LLM:** the labelled eval set's test split is never used for training or tuning. LLM output is schema-validated
  before it is accepted, and impossible dates or invented fields are rejected.

---

## 6. Ethics & legal (applies to every user-facing string)
- An NSQ finding applies to **one specific batch**, not the whole product or company.
- Every view shows the **batch number**, **source alert month**, and a **link to the original CDSCO document**.
- Disclaimer on every page: *"Not medical advice. Data from CDSCO public alerts."*
- Neutral wording only ("number of NSQ batches reported"). Never call a manufacturer fraudulent.
- "Not found" never means "guaranteed safe".
- The risk score reflects **reporting history, not true quality**. Say so wherever it is shown.

---

## 7. Scraping etiquette
- Respect `robots.txt` and site terms. Rate-limit every request (≥3 s per host).
- Cache raw files in RustFS (hash check) so sources are never re-downloaded unnecessarily.
- **Anonymous-visitor rule (ADR 0003):** automate only what a logged-out browser does on its own (public pages,
  files, open JSON, guest tokens issued to every visitor). Never copy request-signing/anti-bot code, call admin
  endpoints, or disguise the client to get past a block. Blocked sources use a manual browser download instead.
- CDSCO and Jan Aushadhi data is not published on the live site until permission is recorded in `docs/permissions.md`.

---

## 8. Email
- Local dev: **Mailpit** container in Docker Compose (catches all mail, web inbox).
- Production: **Brevo** free SMTP.
- Spring Boot (`spring-boot-starter-mail`, watchlist emails) and Airflow (failure alerts) use the same SMTP settings.

---

## 9. Repository layout
```
drugwatch-india/
├── ingestion/        # Downloaders, Airflow DAGs
├── extraction/       # pdfplumber + Camelot parsers, labelled eval set tools
├── spark/            # PySpark cleaning jobs
├── dbt/              # dbt project (staging, intermediate, marts = gold)
├── quality/          # Great Expectations suites
├── ml/               # Feature prep, LightGBM training, SHAP, MLflow
├── ml-serving/       # FastAPI + ONNX Runtime service
├── llm/              # Hugging Face + PEFT LoRA fine-tuning and inference
├── backend/          # Spring Boot application
├── frontend/         # Next.js + Tailwind website
├── infra/            # Docker, compose files, Nginx/Caddy, deploy scripts
├── docs/             # adr/, data-sources.md, benchmarks.md, methodology.md
├── CLAUDE.md
├── DRUGWATCH_PHASES.md
├── PROGRESS.md
└── README.md
```
Every top-level folder exists from Phase 0 (an empty `.gitkeep` holds it in git) and is filled in by its phase.

---

## 10. Common commands
```bash
# Local services (needs .env; template: .env.example)
docker compose up -d --wait     # start all four, wait until healthy
docker compose run --rm rustfs-init   # create raw/bronze/silver buckets (idempotent; re-run after down -v)
docker compose ps               # status + health
docker compose logs -f rustfs   # follow one service's logs
docker compose down             # stop (data kept in named volumes)
docker compose down -v          # stop AND delete all local data

# Python (ingestion/, extraction/; later Python folders work the same way; ADR 0005)
cd ingestion
uv sync                         # create .venv and install the exact versions in uv.lock
uv run pytest                   # tests
uv run ruff check .             # lint (rules in the repo-root ruff.toml)
uv run ruff format .            # auto-format (CI only checks: --check)
uv add <pkg>                    # add a dependency: approved libraries only (§4)

# Downloads into RustFS raw/ (from ingestion/, RustFS up; see docs/data-sources.md §6)
uv run --env-file ../.env python -m drugwatch_ingestion.sources.cdsco_portal --month 2026-09  # or --all, --tab spurious
uv run --env-file ../.env python -m drugwatch_ingestion.sources.cdsco_pdf --list             # then --file-id N / --all
uv run --env-file ../.env python -m drugwatch_ingestion.sources.jan_aushadhi                 # this month's snapshot
uv run --env-file ../.env python -m drugwatch_ingestion.manual_drop FILE --source ... --help  # browser downloads (ADR 0003)
uv run --env-file ../.env python -m drugwatch_ingestion.inventory   # check raw/: sidecars + SHA-256 of every file (exit 1 = problem)

# Extraction (from extraction/, RustFS up)
uv run --env-file ../.env python -m drugwatch_extraction.classify   # text vs scanned + layout family of every CDSCO PDF
uv run --env-file ../.env python -m drugwatch_extraction.extract --all   # every CDSCO PDF -> records with provenance (--show N)
uv run --env-file ../.env python -m drugwatch_extraction.bronze --all    # same, written to bronze/ as Parquet + read back
uv run --env-file ../.env python -m drugwatch_extraction.label           # label eval-set rows (guide: docs/eval-set.md; --redo N)
uv run --env-file ../.env python -m drugwatch_extraction.label --review  # decide parser-vs-second-reader disagreements
uv run --env-file ../.env python -m drugwatch_extraction.evaluate        # parser precision/recall/F1 vs the labels
uv run --env-file ../.env python -m drugwatch_extraction.portal_bronze --all   # portal JSON -> bronze/cdsco-portal/
# (eval_set --sample drew eval/manifest.csv once; it refuses to redraw)
uv run --env-file ../.env python -m drugwatch_extraction.second_reader --render|--compare   # AI-assisted labels

# Spark (from spark/, RustFS up; needs Java 17+). First S3 run only: prefetch avoids a risky 686 MB
# single-stream download on a slow link (resumable pieces, SHA-256 checked; ADR 0008).
uv run python -m drugwatch_spark.prefetch                         # once per machine, no .env needed
uv run --env-file ../.env python -m drugwatch_spark.read_bronze   # Spark reads both bronze datasets, prints counts
uv run --env-file ../.env python -m drugwatch_spark.clean_bronze  # whitespace-cleaning report (read-only; step 2)
uv run --env-file ../.env python -m drugwatch_spark.fix_portal_batch  # 9 portal rows w/ a wrong batch_no: before/after
uv run --env-file ../.env python -m drugwatch_spark.parse_dates   # portal dates -> real dates; flags mfg_date >= expiry_date
uv run --env-file ../.env python -m drugwatch_spark.parse_pdf_dates  # same, for PDF rows (5 proven-safe formats, 88.8% coverage)
uv run --env-file ../.env python -m drugwatch_spark.dosage_form   # dosage form from product names (88.9% filled)
```

**Local service ports** (all bound to 127.0.0.1; Postgres and Redis are shifted so they don't clash with OpsPilot):

| Service | From your Mac | Inside the Docker network |
|---|---|---|
| PostgreSQL | `localhost:5433` | `postgres:5432` |
| Redis | `localhost:6380` | `redis:6379` |
| RustFS S3 API | `localhost:9000` | `rustfs:9000` |
| RustFS console | http://localhost:9001/rustfs/console/ | — |
| Mailpit SMTP | `localhost:1025` | `mailpit:1025` |
| Mailpit inbox | http://localhost:8025 | — |

S3 clients talking to RustFS must use **path-style addressing** (see ADR 0002).
If S3 calls fail with `RequestTimeTooSkewed` after the Mac has slept, Docker's VM clock has drifted more than
15 min from the Mac's: quit and restart Docker Desktop. Wrap long local jobs in `caffeinate -i` to stop sleep.

---

## 11. Definition of done (every step)
- [ ] Tests pass
- [ ] Verified by actually running it, with output shown
- [ ] No secrets committed; `.env.example` updated if new config was added
- [ ] `PROGRESS.md` updated, plus an ADR if a stack or design decision changed
