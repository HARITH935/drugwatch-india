# DrugWatch India

> **Is my medicine batch flagged?** A public medicine quality and price intelligence platform built on
> the "Not of Standard Quality (NSQ) / Spurious" drug alerts that CDSCO publishes every month.

**Status:** planning. Nothing is built or deployed yet; see [PROGRESS.md](PROGRESS.md).

> ⚠️ **Not medical advice. Data from CDSCO public alerts.** An NSQ finding applies to one specific batch,
> not to the whole product or manufacturer. "Not found" does not mean "guaranteed safe".

---

## The problem

Every month, India's drug regulator (CDSCO) tests medicine samples collected from pharmacies and
distributors, and publishes the batches that fail as PDF lists. Those PDFs are hard to find, hard to
read and impossible to search. A patient holding a strip of tablets has no practical way to check
whether that exact batch failed.

## What DrugWatch India will do

- **Batch checker:** enter a medicine name and batch number and see whether it appears in any alert,
  with the alert month, failure reason, reporting lab and a link to the original CDSCO PDF.
- **Public dashboards:** failure trends by manufacturer, state and drug class.
- **Price comparison:** branded price vs NPPA ceiling price vs Jan Aushadhi generic for the same salt.
- **Manufacturer risk score:** an ML estimate of how likely a manufacturer is to appear in upcoming
  alerts, with SHAP explanations. It reflects reporting history, not true product quality.
- **Watchlist email alerts** when a watched medicine appears in a new monthly alert.

## How it works

```
CDSCO / NPPA / Jan Aushadhi PDFs
  → Airflow (monthly) → RustFS raw/
  → pdfplumber + Camelot (fine-tuned LLM fallback for hard rows) → bronze/
  → PySpark cleaning + RapidFuzz entity resolution + Great Expectations → silver/
  → dbt → gold (marts in PostgreSQL)
  → Superset dashboards · LightGBM risk model (ONNX + FastAPI) · Spring Boot API
  → Next.js website
```

Data layers: **raw → bronze → silver** (Parquet in RustFS) **→ gold** (dbt marts in PostgreSQL).
The full architecture is in [DRUGWATCH_PHASES.md §7](DRUGWATCH_PHASES.md).

## Tech stack

| Area | Tools |
|---|---|
| Data pipeline | Python, Airflow, pdfplumber, Camelot, RustFS, PySpark, RapidFuzz, Great Expectations |
| Warehouse & analytics | PostgreSQL, dbt, SQL, Apache Superset, Pandas |
| Machine learning | LightGBM, SHAP, MLflow, ONNX, onnxmltools, ONNX Runtime, FastAPI |
| LLM | Hugging Face Transformers, PEFT (LoRA) |
| Backend | Java, Spring Boot, Spring Security + JWT, Spring Data JPA, Flyway, Redis, Spring Mail, OpenAPI, Testcontainers + JUnit |
| Frontend | TypeScript, Next.js, Tailwind CSS, Superset embedded SDK |
| Email | Mailpit (local), Brevo SMTP (production) |
| DevOps | Docker, Docker Compose, GitHub Actions, cloud VM, Nginx / Caddy |

Why each tool was chosen: [docs/adr/0001-stack-choice.md](docs/adr/0001-stack-choice.md).

## Data sources

- CDSCO NSQ / spurious drug alerts (central and state labs), monthly PDFs
- NPPA ceiling price lists
- Jan Aushadhi product list

Downloads respect `robots.txt` and site terms, are rate-limited, and are cached so sources are never
re-downloaded unnecessarily.

## Repository layout

```
ingestion/   extraction/   spark/   dbt/   quality/   ml/   ml-serving/
llm/   backend/   frontend/   infra/   docs/
```

Each folder is an empty placeholder until its build phase fills it in.

## Documentation

- [DRUGWATCH_PHASES.md](DRUGWATCH_PHASES.md): full plan (features, data model, phases, API, ML and LLM design)
- [PROGRESS.md](PROGRESS.md): live build status
- [docs/adr/](docs/adr/): architecture decision records

## Local setup

Needs Docker Desktop. Starts PostgreSQL, RustFS (S3-compatible storage), Redis and Mailpit:

```bash
cp .env.example .env      # then fill in the blank values (e.g. with: openssl rand -hex 16)
docker compose up -d --wait
docker compose ps         # all four should say "healthy"
docker compose run --rm rustfs-init   # create the raw/bronze/silver buckets (safe to re-run)
```

| Service | Address |
|---|---|
| PostgreSQL | `localhost:5433` |
| RustFS console | http://localhost:9001/rustfs/console/ |
| Mailpit inbox | http://localhost:8025 |

More setup steps are added as the build progresses.
