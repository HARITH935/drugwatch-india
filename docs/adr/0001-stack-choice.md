# ADR 0001 — Stack choice

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** Harith (project owner)

---

## Context

DrugWatch India is an end-to-end system on real, messy, monthly government PDFs: data engineering →
analytics → ML → LLM → backend → frontend → deployment. The stack has to cover that whole path with
industry-standard tools. It is then **locked**, because adding tools mid-build is a known way to stall a
project (plan §17, "Too many new tools").

## Decision

Use the mandatory stack in `DRUGWATCH_PHASES.md` §6. No substitutions or removals without approval. Any
addition needs approval first and is recorded in an ADR.

| Layer | Choice | Why |
|---|---|---|
| Pipelines, ML, LLM | Python | Best ecosystem for PDF parsing, Spark, ML and LLM fine-tuning |
| Orchestration | Airflow | Standard scheduler for a monthly pipeline plus historical backfills |
| PDF extraction | pdfplumber, Camelot | pdfplumber gives character-level control for messy layouts; Camelot is strong on tables with clear borders |
| Data lake | ~~MinIO~~ → **RustFS** | S3-compatible and runs locally in Docker; the same code would work against S3. *Superseded by ADR 0002: MinIO's community edition was discontinued.* |
| Processing | Apache Spark (PySpark) | Full-history reprocessing and future sources (see addition 4) |
| Transformation | dbt | Version-controlled SQL models with built-in tests, docs and lineage |
| Data quality | Great Expectations | Declarative checks on every pipeline run |
| Database | PostgreSQL | One free, well-supported database for the gold layer and the app tables |
| Analytics | Apache Superset, Pandas | Open-source dashboards; Pandas for exploration |
| Data science | LightGBM, SHAP, RapidFuzz, MLflow | Strong on small tabular data; explainable; fast fuzzy matching; experiment tracking and model registry |
| Model serving | ONNX, ONNX Runtime, FastAPI | Inference independent of the training environment; FastAPI is Python-native |
| LLM | Hugging Face Transformers, PEFT (LoRA) | Fine-tune a small open model on a free or cheap GPU |
| Backend | Java, Spring Boot, Spring Security + JWT, Spring Data JPA, Flyway, Redis, Testcontainers + JUnit, OpenAPI | Industry-standard API stack: auth, data access, versioned migrations, caching, tests against real dependencies, API docs |
| Frontend | TypeScript, Next.js, Tailwind CSS | Typed, server-rendered pages; fast mobile-first styling |
| DevOps | Docker, Docker Compose, GitHub Actions, cloud VM, Nginx / Caddy | Reproducible containers, CI/CD, low-cost hosting, HTTPS |

---

## Approved additions (2026-11-03)

### 1. Superset embedded SDK + guest tokens
- **Decision:** use `@superset-ui/embedded-sdk` in Next.js (Phase 11). Spring Boot gets guest tokens from
  the Superset API and serves them from a guest-token endpoint (Phase 9).
- **Why:** the website embeds Superset dashboards. The SDK with guest tokens is Superset's supported way
  to do that without giving visitors Superset logins.
- **Consequences:**
  - Superset needs embedding enabled (`EMBEDDED_SUPERSET`) and a read-only guest role.
  - Spring Boot holds a Superset service-account credential, from env vars only.
  - Superset must be reachable by browsers through the reverse proxy.
  - The guest-token endpoint is public, so it is rate-limited and only serves allowlisted dashboards.

### 2. Email: `spring-boot-starter-mail`, Mailpit, Brevo
- **Decision:** `spring-boot-starter-mail` sends watchlist emails (Phase 9). A Mailpit container in Docker
  Compose handles local dev (Phase 0); Brevo's free SMTP handles production (Phase 12). Airflow failure
  alerts (Phase 5) use the same SMTP settings.
- **Why:** watchlist alerts and pipeline failure alerts both need email, and the original stack had no
  way to send it. Mailpit lets every email be tested locally without sending real mail. Brevo provides
  free production SMTP.
- **Consequences:**
  - SMTP credentials come from env vars only, and `.env.example` gets SMTP settings.
  - Switching from dev to production is a config change, not a code change.
  - Brevo's free tier has a daily sending cap, so watch email volume.

### 3. onnxmltools
- **Decision:** approved for Phase 8.
- **Why:** ONNX Runtime can't load a LightGBM model directly; onnxmltools converts it to ONNX.
- **Consequences:** Phase 8 already includes a step to verify that ONNX predictions match the original model.

### 4. Keep Spark, and measure it
- **Decision:** keep PySpark for bronze → silver. Add a Phase 3 step that runs the same cleaning job in
  Pandas and in PySpark, recording runtime and peak memory in `docs/benchmarks.md`.
- **Why:** at current data volume Spark is expected to be overkill. It is kept for full-history
  reprocessing, future data sources, and learning. The benchmark replaces a guess with a measured number.
- **Consequences:** one extra Phase 3 step, and a Pandas version of the cleaning job is kept for the comparison.

### 5. Gold layer = dbt marts
- **Decision:** the data layers are raw → bronze → silver (MinIO buckets) → gold (dbt marts in
  PostgreSQL: the star schema plus the `mart_*` tables). dbt `staging` and `intermediate` models are
  build steps, not a separate layer.
- **Why:** the plan's glossary named four layers, but the architecture stopped at silver plus a
  "warehouse". This gives one consistent naming everywhere.
- **Consequences:**
  - MinIO keeps three buckets.
  - Superset, the ML pipeline and the API read only from gold.

---

## Overall consequences

- **Positive:** covers the full data → ML → LLM → product → deployment path with widely used tools, and
  every tool has a clear job.
- **Negative:** many moving parts for one developer, and some tools (Spark) are larger than the current
  data volume needs.
- **Mitigation:** build one phase at a time and finish each before the next. Measure trade-offs (the
  Spark benchmark) instead of assuming them.
