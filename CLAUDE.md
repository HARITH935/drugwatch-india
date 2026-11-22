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
├── ingestion/        # Downloaders (the DAGs live in orchestration/, ADR 0012)
├── extraction/       # pdfplumber + Camelot parsers, labelled eval set tools
├── spark/            # PySpark cleaning jobs
├── dbt/              # dbt project (dbt_staging, dbt_intermediate, gold marts)
├── quality/          # Great Expectations suites
├── warehouse/        # silver -> Postgres staging loader (ADR 0011)
├── orchestration/    # Airflow DAGs + its config wrapper (ADR 0012)
├── analytics/        # exploration notebook over gold (ADR 0013)
├── ml/               # LightGBM risk model, SHAP, MLflow tracking (ADR 0015, ADR 0016)
├── ml-serving/       # FastAPI + ONNX Runtime risk service (ADR 0017)
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
uv run --env-file ../.env python -m drugwatch_spark.strength      # strengths as a list (38.0% of names print one)
uv run --env-file ../.env python -m drugwatch_spark.brand_generic # brand vs generic, only where unambiguous (~20-27%)
uv run --env-file ../.env python -m drugwatch_spark.manufacturer_name  # strip address, expand Pvt./Ltd. (~95-98%)
uv run --env-file ../.env python -m drugwatch_spark.manufacturer_cluster  # RapidFuzz: 3,320 names -> 2,734 makers
uv run --env-file ../.env python -m drugwatch_spark.manufacturer_review --batches  # accept the 100 mechanical pairs
uv run --env-file ../.env python -m drugwatch_spark.manufacturer_review   # decide the 160 borderline ones (y/n/q)
uv run --env-file ../.env python -m drugwatch_spark.failure_category  # failure reasons -> categories (ADR 0009)
uv run --env-file ../.env python -m drugwatch_spark.deduplicate    # one row per finding; proves dedup is idempotent
uv run --env-file ../.env python -m drugwatch_spark.build_silver   # every step together: bronze -> silver (--dry-run)
uv run --env-file ../.env python -m drugwatch_spark.pandas_pipeline   # the same job in pandas (step 9)
uv run --env-file ../.env python -m drugwatch_spark.compare_engines   # prove both engines produce the same silver
uv run --env-file ../.env python -m drugwatch_spark.benchmark --repeat 3  # time + peak memory (docs/benchmarks.md)

# Data quality (from quality/, RustFS up). Reads silver with pyarrow, not Spark: no JVM, seconds.
uv run --env-file ../.env python -m drugwatch_quality.suite    # validate silver (exit 1 = silver is wrong)
uv run --env-file ../.env python -m drugwatch_quality.silver   # what silver holds: row count, columns, fill rates

# Warehouse (from warehouse/, RustFS + Postgres up). Full refresh in one transaction; re-runnable.
uv run --env-file ../.env python -m drugwatch_warehouse.load_silver            # silver -> staging.silver_nsq
uv run --env-file ../.env python -m drugwatch_warehouse.load_silver --dry-run  # read and check, write nothing
docker compose exec postgres psql -U drugwatch -c "select count(*) from staging.silver_nsq"  # check it landed

# dbt (from dbt/, Postgres up and silver loaded). dbt finds the repo-root .env by itself, but the
# --env-file keeps these commands the same shape as every other one above.
uv run --env-file ../.env dbt build            # build every model, then run its tests
uv run --env-file ../.env dbt debug            # check the connection and the config
uv run --env-file ../.env dbt source freshness # how old the loaded silver is (warn 45d / error 75d)
uv run dbt parse                               # check the SQL/YAML parses; no database needed
uv run --env-file ../.env dbt docs generate    # lineage graph + catalog from the model descriptions
uv run --env-file ../.env dbt docs serve --port 8081  # browse it (Ctrl-C to stop)

# Airflow (from orchestration/, Postgres up). Airflow runs on your Mac, not in Docker (ADR 0012);
# its DAG tasks shell out to the uv commands above. The wrapper applies every AIRFLOW__* setting.
uv run --env-file ../.env python -m drugwatch_orchestration.cli standalone  # scheduler + UI on :8082
uv run --env-file ../.env python -m drugwatch_orchestration.cli dags list   # what Airflow has parsed
uv run --env-file ../.env python -m drugwatch_orchestration.cli dags reserialize   # re-parse dags/ now
uv run --env-file ../.env python -m drugwatch_orchestration.cli dags test raw_inventory  # run one, for real
uv run --env-file ../.env python -m drugwatch_orchestration.cli dags test monthly_pipeline  # the whole pipeline (~20 min)
uv run --env-file ../.env python -m drugwatch_orchestration.cli tasks render monthly_pipeline download_portal_nsq 2026-11-10  # see a templated command
uv run --env-file ../.env python -m drugwatch_orchestration.cli db migrate  # first run only (needs the airflow DB)
uv run --env-file ../.env pytest               # DAG integrity: every DAG parses, no cycles, retries set
# The run log (ops schema in Postgres): what each run processed and changed, and what failed
docker compose exec postgres psql -U drugwatch -c "select run_id, status, raw_files, raw_files_added, silver_rows, silver_rows_added, dbt_nodes_passed, quality_check from ops.pipeline_run order by recorded_at desc limit 5"
docker compose exec postgres psql -U drugwatch -c "select task_id, state, round(duration_seconds) s from ops.pipeline_task where run_id = (select run_id from ops.pipeline_run order by recorded_at desc limit 1) order by started_at"

# Analytics (from analytics/, Postgres up with gold loaded). Reads gold ONLY, in a read-only
# transaction. Notebooks are committed with outputs cleared - repo-checks.sh fails otherwise.
uv run --env-file ../.env jupyter lab                     # open the notebook and explore
uv run --env-file ../.env jupyter nbconvert --execute --to notebook --stdout notebooks/01-explore-gold.ipynb >/dev/null  # does it still run?
uv run jupyter nbconvert --clear-output --inplace notebooks/01-explore-gold.ipynb   # before committing
uv run --env-file ../.env pytest           # the gold reader, incl. that writes are refused
# The drug-class vocabulary (ADR 0014). Nothing in CDSCO classifies a medicine, so a person
# accepts or rejects each proposed ingredient -> class; whatever is rejected stays Unclassified.
uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review --batches   # 187 clear, per class
uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review            # 28 judgement calls
uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review --seed      # -> dbt/seeds/
uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review --coverage  # what it covers

# Superset dashboards (from the repo root, stack up). Reads gold ONLY, as the superset_reader role.
docker compose run --rm superset-init          # first run only: migrate metadata + create the admin
docker compose up -d superset                  # UI: http://localhost:8088 (login from .env)
bash infra/superset/register_gold_database.sh  # register/re-point the 'DrugWatch gold' connection
bash infra/superset/smoke_test.sh              # proves gold is readable and staging/ops are refused
# Dashboards are provisioned from code, never clicked (idempotent: re-running updates in place)
set -a && . ./.env && set +a && python3 infra/superset/build_manufacturer_dashboard.py
set -a && . ./.env && set +a && python3 infra/superset/build_states_dashboard.py
set -a && . ./.env && set +a && python3 infra/superset/build_spurious_dashboard.py
set -a && . ./.env && set +a && python3 infra/superset/build_drug_class_dashboard.py
set -a && . ./.env && set +a && python3 infra/superset/verify_charts.py  # every chart must return rows
# Anonymous (public) access: a minimal hand-built role, NOT PUBLIC_ROLE_LIKE=Gamma (which would let
# strangers edit dashboards). MUST be re-run after adding a dataset: Superset's dataset and chart
# list APIs filter by datasource_access, so an ungranted dataset is invisible even to the admin.
docker compose exec -T superset python - < infra/superset/configure_public_role.py
python3 infra/superset/public_access_test.py   # what a logged-out stranger can and cannot do
# A dashboard with NO charts is invisible even to an admin (Superset resolves dashboard access
# through the datasources of its charts), so a build that died before attaching them leaves a
# dashboard whose slug is taken and which nothing can find. This brings it back:
set -a && . ./.env && set +a && python3 infra/superset/attach_orphan_dashboard.py
# Dashboards as code: export to infra/superset/assets/ (refuses if a real password is in the bundle)
set -a && . ./.env && set +a && python3 infra/superset/export_assets.py
set -a && . ./.env && set +a && bash infra/superset/import_assets.sh  # rebuild them from the repo
# First run only: create Superset's own database and its read-only role
docker compose exec postgres psql -U drugwatch -c "CREATE DATABASE superset"
set -a && . ./.env && set +a && docker compose exec -T postgres psql -U drugwatch -v ON_ERROR_STOP=1 -v reader_password="$SUPERSET_READER_PASSWORD" -f - < infra/postgres/superset_reader.sql
# First time only: create Airflow's own database beside drugwatch's
docker compose exec postgres psql -U drugwatch -c "CREATE DATABASE airflow"

# ML: the manufacturer risk score (from ml/, Postgres up with gold loaded; ADR 0015, ADR 0016)
# Reads gold.mart_ml_features ONLY, in a read-only transaction. MLflow tracks every run.
uv sync                                    # lightgbm, shap, mlflow, scikit-learn
uv run --env-file ../.env python -m drugwatch_ml.smoke_test  # foundations: gold + MLflow + artifacts
uv run --env-file ../.env python -m drugwatch_ml.show_protocol  # the train/validate/test folds
uv run --env-file ../.env python -m drugwatch_ml.run_baselines  # the bar LightGBM must clear
# caffeinate: a sleeping Mac looks exactly like slow code (a 40-trial search once took 141 min)
caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.train --trials 40  # random search
# The single-use test. Exits 1 if the model fails decision C's bar; that is a result, not a bug.
caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.evaluate
caffeinate -i uv run --env-file ../.env python -u -m drugwatch_ml.publish  # SHAP + register (docs/model-card.md)

# Risk service (from ml-serving/, MLflow up with a registered model; ADR 0017)
# Reads NOTHING from Postgres: Phase 9's API reads gold and posts the 28 features.
uv sync                                    # fastapi, onnxruntime, onnxmltools (+ ../ml for wording)
uv run --env-file ../.env python -m drugwatch_serving.build_onnx   # export + verify vs the original
uv run --env-file ../.env pytest           # incl. that /predict and /explain return the same score
uv run --env-file ../.env uvicorn drugwatch_serving.app:app --port 8000  # run it on the Mac
docker compose up -d --build --wait risk-api   # or in Docker: http://localhost:8000/docs
curl -s localhost:8000/health | python3 -m json.tool    # which model version is answering
uv run python -m drugwatch_serving.benchmark --url http://localhost:8000  # p50/p95/p99 latency

# Backend API (from backend/, Phase 9; ADR 0018). Java 21 + Spring Boot 4.2, built with Maven.
# ./mvnw, not mvn: the wrapper pins Maven 3.10.0, so this Mac and CI run the same build tool.
./mvnw verify                  # compile, run every test, and fail if anything is unformatted
./mvnw spotless:apply          # format the code (the Java equivalent of `ruff format`)
./mvnw test -Dtest=ArchitectureTest   # just the layering rules
./mvnw spring-boot:run         # run the API on http://localhost:8080 (health: /actuator/health)
# Auth (step 3). Register -> the verification link arrives in Mailpit (http://localhost:8025).
curl -s -X POST localhost:8080/api/v1/auth/register -H 'Content-Type: application/json' -d '{"email":"you@example.com","password":"a-long-enough-password"}'
curl -s -X POST localhost:8080/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"you@example.com","password":"a-long-enough-password"}'
# Watchlist (step 4). Needs the access token from login, and a VERIFIED address to be emailed.
curl -s -X POST localhost:8080/api/v1/watchlist -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"term":"telmisartan"}'
curl -s localhost:8080/api/v1/watchlist -H "Authorization: Bearer $TOKEN"
# Notifications run on a daily cron and only cover alert months AFTER a watch was created, so
# adding one never emails the back catalogue. Override the schedule locally with:
#   --drugwatch.watchlist.cron='0/30 * * * * *'
# Risk score (step 5). Proxies to the Phase 8 service; needs risk-api up, else "unavailable".
# RISK_API_URL=http://127.0.0.1:8000 locally (http://risk-api:8000 inside Docker).
curl -s localhost:8080/api/v1/manufacturers/<id>/risk | python3 -m json.tool
# Caching + rate limiting (step 6). Cache keys carry the alert month, so a monthly load
# invalidates everything by itself - nothing to flush. Inspect or clear:
docker compose exec redis redis-cli --scan --pattern 'drugPages*'
docker compose exec redis redis-cli --scan --pattern 'ratelimit:*'
# Public lookups are limited per caller (RATE_LIMIT_PER_MINUTE, default 60); auth and the
# watchlist are not, because a shared office IP would lock everyone out of their account.
# First run only: the drugwatch_api role (SELECT on gold, owns the `app` schema, nothing else)
set -a && . ./.env && set +a && docker compose exec -T postgres psql -U drugwatch -v ON_ERROR_STOP=1 -v api_password="$API_DB_PASSWORD" -f - < infra/postgres/api_role.sql
# Flyway migrates `app` at startup. The privilege tests need the real DB and skip without it:
set -a && . ../.env && set +a && ./mvnw verify   # from backend/, runs them too
uv run --env-file ../.env pytest           # incl. that the feature list matches the live mart
# First time only: MLflow's own database and its artifact bucket
docker compose exec postgres psql -U drugwatch -c "CREATE DATABASE mlflow"
docker compose run --rm rustfs-init        # creates the mlflow bucket too (idempotent)
docker compose up -d --wait mlflow         # UI: http://localhost:5050
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
| Airflow UI | http://localhost:8082 | — (runs on the host, not in Docker) |
| Superset | http://localhost:8088 | `superset:8088` |
| MLflow | http://localhost:5050 | `mlflow:5000` |
| Risk API | http://localhost:8000 | `risk-api:8000` |
| Backend API | http://localhost:8080 | `backend:8080` |

S3 clients talking to RustFS must use **path-style addressing** (see ADR 0002).
If S3 calls fail with `RequestTimeTooSkewed` after the Mac has slept, Docker's VM clock has drifted more than
15 min from the Mac's: quit and restart Docker Desktop. Wrap long local jobs in `caffeinate -i` to stop sleep.

---

## 11. Definition of done (every step)
- [ ] Tests pass
- [ ] Verified by actually running it, with output shown
- [ ] No secrets committed; `.env.example` updated if new config was added
- [ ] `PROGRESS.md` updated, plus an ADR if a stack or design decision changed

---

## 12. Token efficiency
- Don't restate code/files back to me that I can already see.
- No step-by-step narration between tool calls ("Now I will...").
- Use targeted reads (grep, offset/limit) instead of reading whole files.
- Don't re-read a file you just edited to verify - trust the edit result.
- Batch independent tool calls into one turn.
- Keep summaries short: what changed, where, next step only.
