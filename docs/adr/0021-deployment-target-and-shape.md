# ADR 0021 — Deploy on free managed platforms; the pipeline stays on the Mac

- **Status:** Accepted
- **Date:** 2026-11-26
- **Decided by:** Harith (project owner), Phase 12 planning
- **Affects:** Phase 12 (every step), `infra/`, CI, ADR 0012's open question, ADR 0016/0017
  (MLflow is not deployed), plan §6 DevOps row ("Cloud VM, Nginx / Caddy") and §15

---

## Context

Phase 12 puts the system on the public internet (plan §9, §15, §16). Three constraints decided
the shape, all checked rather than assumed:

- **Cost must be ₹0, with no credit card.** Oracle Cloud's free tier, AWS, GCP and Fly.io all
  require a credit card; DigitalOcean's student credit needs a card or a PayPal account that
  itself asks for one; Azure for Students' $100 credit lasts ~1.5-3 months on a server big
  enough. A paid Indian VPS (~₹800/month) was offered and declined.
- **The full stack peaks at ~8-9 GB** (web services ~3.5 GB, MLflow alone ~1.9 GB; Airflow
  ~1.5 GB; one Spark run 2.7 GB - `docs/benchmarks.md`). No free tier offers that in one place.
- **The data is small** (~300 MB total; the `drugwatch` database ~71 MB), so free managed
  databases are big enough.

## Decision

**Split the system by what it needs, and put each piece where it is free:**

| Piece | Where | Notes |
|---|---|---|
| Next.js website | **Vercel** (Hobby) | Builds from `frontend/`; HTTPS on `*.vercel.app` |
| Spring Boot API | **Render** free web service, from a Dockerfile | 512 MB; sleeps after 15 min idle (cold start ~30-60 s) - kept awake by the uptime monitor's pings, inside the 750 free hours/month for one service |
| Risk service (FastAPI + ONNX) | **Hugging Face Space** (Docker, free CPU), **private** | The registered model is **baked into the image** at build time, so MLflow is not deployed. Private: only the API, holding a read token, can call it (§15: FastAPI not public) |
| Superset | **Hugging Face Space** (Docker, free CPU), public | Must be reachable for the embedded iframe (§15 already allows this). Metadata in Neon |
| PostgreSQL (gold, `app`, Superset metadata) | **Neon** free (0.5 GB) | TLS required; the same least-privilege roles as local (`drugwatch_api`, `superset_reader`) |
| Redis (cache, rate limits) | **Upstash** free | TLS required |
| Email | **Brevo** free | From a verified single sender (no own domain, so deliverability is weaker - accepted) |
| Uptime | **UptimeRobot** free | Off-platform, so it notices when a platform is down |
| Pipeline: Airflow, Spark, RustFS, MLflow | **Stays on the Mac** (ADR 0012 unchanged) | A new final step publishes the gold schema to Neon in one transaction |
| CI/CD | **GitHub Actions** | Tests pass → call each platform's deploy hook. Platform auto-deploy on git push is turned **off**, so a failing test can never deploy |

**Before CDSCO permission is recorded** (CLAUDE.md §7): the site is live but behind a password
checked in Next.js's `proxy.ts`, switched by one environment variable (Vercel's own password
protection is a paid feature). Launch = unset it.

**Secrets** live only in each platform's environment-variable settings and in GitHub Actions
secrets; production gets freshly generated passwords and JWT keys. Nothing new in the repo.

**Backups:** Neon's built-in restore window, plus a weekly GitHub Actions job that takes a
`pg_dump`, encrypts it with `openssl` (already on the runner) and keeps it as a 90-day
artifact; `raw/` stays on the Mac plus one off-site copy in a private Hugging Face dataset repo.
A restore into an empty database is tested, not assumed.

## Consequences

- **Plan §6's "Cloud VM, Nginx / Caddy" is replaced** by managed platforms that terminate HTTPS
  themselves. Docker and GitHub Actions stay.
- **§15 "internal services not exposed publicly":** Neon and Upstash are reachable from the
  internet by design (that is how managed databases work), protected by TLS, strong generated
  passwords and least-privilege roles. The risk service stays private (a private Space + token).
- **MLflow and RustFS are not in production.** The risk service no longer reads the registry at
  startup in production; it loads a model file built into its image, and the ONNX-vs-LightGBM
  parity check still runs at startup (ADR 0017's guarantee is kept).
- **The monthly pipeline runs only while the Mac is awake**; Airflow catches up on the next
  start. Accepted for a monthly job; recorded honestly rather than hidden.
- **Cold starts:** a sleeping Render service or Space makes the first visit slow. Documented on
  the About page if it proves noticeable.
- Free tiers change their terms. Each platform is replaceable on its own because every service
  is a Docker image or a plain Next.js build configured only through environment variables.

## Alternatives rejected

| Option | Why not |
|---|---|
| Oracle Cloud Always Free (24 GB ARM) | Requires a credit card |
| Hostinger KVM 2 (8 GB, UPI) | ~₹800/month; Harith chose ₹0 |
| Azure for Students | Credit runs out in ~1.5-3 months, then the site goes down |
| DigitalOcean (Student Pack) | Card or PayPal, and PayPal's address check asks for a card |
| Everything on Render | 512 MB per service and 750 hours/month shared - Superset alone needs more |
| Render's free Postgres | Expires after 30 days |
| Airflow + Spark in the cloud | No free tier has ~4 GB for a monthly job; GitHub Actions' US IP ranges also risk being refused by CDSCO |
