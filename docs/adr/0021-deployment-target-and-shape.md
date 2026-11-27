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
| Risk service (FastAPI + ONNX) | **Render** free web service, from a Dockerfile, same account as the API | The registered model is **baked into the image** at build time, so MLflow is not deployed. Not on any allowlist a browser could reach - only the API, holding `RISK_API_TOKEN`, can call it (§15: FastAPI not public). See amendment below for why this moved off Hugging Face |
| Superset | **Render** free web service, from a Dockerfile, same account | Must be reachable for the embedded iframe (§15 already allows this). Metadata in Neon. **Unverified here:** the 512 MB limit - step 3's own job to measure, same way step 0 measured the other two |
| PostgreSQL (gold, `app`, Superset metadata) | **Neon** free (0.5 GB), **Singapore** | TLS required; the same least-privilege roles as local (`drugwatch_api`, `superset_reader`). Region matters - see the 2026-11-27 amendment |
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
| Hugging Face Spaces for the risk service and Superset (original plan, reversed below) | HF restricted free accounts to Static Spaces and a small Gradio/ZeroGPU allowance around mid-2026 - Docker Spaces now need a paid plan. Found, not predicted: this was accepted and working when step 0 planned around it |
| Oracle Cloud Always Free (24 GB ARM) | Requires a credit card |
| Hostinger KVM 2 (8 GB, UPI) | ~₹800/month; Harith chose ₹0 |
| Azure for Students | Credit runs out in ~1.5-3 months, then the site goes down |
| DigitalOcean (Student Pack) | Card or PayPal, and PayPal's address check asks for a card |
| Everything on Render (original reasoning, now reversed below) | 512 MB per service and 750 hours/month shared - Superset alone was assumed to need more, untested at the time |
| Render's free Postgres | Expires after 30 days |
| Airflow + Spark in the cloud | No free tier has ~4 GB for a monthly job; GitHub Actions' US IP ranges also risk being refused by CDSCO |

## Amendment, 2026-11-26 (Phase 12 step 2): Hugging Face Spaces reversed, both moved to Render

Mid-step, creating the risk service's Space hit a wall that did not exist when this ADR was
written: Hugging Face now shows **"Docker (paid)"** on `huggingface.co/new-space` for most free
accounts - a platform policy change, not a misconfiguration. Free accounts are limited to Static
Spaces and a small Gradio/ZeroGPU allowance. Checked, not assumed: Render's own docs confirm a
`Dockerfile Path` field exists precisely so one repo can back several independent services, each
pointing at a different Dockerfile - `backend/Dockerfile` and
`infra/ml-serving/Dockerfile.space` can sit in the same account Render's step 4 already needs.

- **Risk service → Render**, as a second free web service in the same account as the Spring Boot
  API. Nothing about the image or the step 2 token check changes - `RISK_API_TOKEN` does the same
  job a private Space's own gate would have, and was built for exactly this reason (ADR 0017's
  amendment: "a private Space is still reachable by any server-to-server call").
- **Superset → Render**, as a third. This reverses this ADR's own "Everything on Render" rejection
  above, whose stated reason - Superset needs more than 512 MB - was never actually measured.
  Step 3 must measure it the same way step 0 measured the backend and risk service, before
  assuming Render fits; if it does not, Superset specifically needs a different home and this ADR
  gets amended again.
- **Three free services now share the 750-hour/month pool** instead of one. Each spins down
  after 15 minutes without traffic and consumes no hours while asleep, so this is accepted rather
  than measured in advance - revisit if real usage proves it wrong.

## Amendment, 2026-11-27 (Phase 12 step 3): every managed service sits in Singapore

This ADR named the platforms but never said **where**, and the defaults did not agree: step 1 took
Neon's suggested `us-east-2` (Ohio) while step 2's Render service landed in Singapore. Nothing
noticed until Superset's first-run migrations crawled - **156 migrations in 30 minutes, ~11.5 s
each**, against a database that answers a local query in milliseconds. The cause was not Superset:
it was ~220 ms of Pacific round trip per statement, and the same connection dropped twice mid-run
with `SSL SYSCALL error: EOF detected`.

A slow one-off migration is a nuisance. The same latency on **every request the live site makes**
is the actual problem: the batch checker runs several queries per lookup, so a page would spend
most of a second waiting on the network before doing any work.

**Decision: all managed services live in Singapore (`ap-southeast-1`)** - Render already did, so
Neon moves. Neon's free plan allows one project, so this means a new project rather than a region
switch, and redoing step 1 against it. That is cheap precisely because step 1 was written as
scripts rather than dashboard clicks: `publish_gold.sh` (with its own row-count check),
`neon_api_role.sql`, `neon_superset_reader.sql`, one `CREATE EXTENSION pg_trgm` and one
`CREATE DATABASE superset`.

Singapore rather than a US region because the audience is in India: Render serves the pages and
Neon answers the queries, so putting both near the readers beats putting both near nothing in
particular. **Region is now part of this ADR, not a per-service default** - anything added later
goes to Singapore too, or says in writing why not.

**Measured, from this Mac, five `select 1` statements in one open session** (so connection setup
is excluded - this is the per-statement cost a migration or a request actually pays):

| Neon region | Per statement |
|---|---|
| `us-east-2` (Ohio) | 348, 404, 421, 442, 462 ms - mean **416 ms** |
| `ap-southeast-1` (Singapore) | 53, 56, 71, 87, 94 ms - mean **72 ms** |

**5.8x**, and that is still measured over an Indian consumer link. The pairing production actually
uses - Render Singapore to Neon Singapore, one region - pays neither leg of that.
