# ADR 0016 — MLflow runs as a Compose service, with Postgres and RustFS behind it

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decided by:** Harith (project owner)
- **Affects:** `docker-compose.yml`, `infra/mlflow/`, `ml/` (Phase 7), and Phase 8's model loading

---

## Context

Plan §9 Phase 7 step 8: *"Track all runs and register the best model in MLflow."* MLflow can do that
three ways - a local directory of files, a local directory plus a SQLite file, or a server with a
real database behind it - and the choice is not reversible for free: runs recorded one way do not
move to another without exporting and re-importing them.

The deciding constraint is **Phase 8, not Phase 7**. Phase 8 builds a FastAPI container that loads
the registered model, and *"load model version from MLflow"* is one of its steps. A directory on
the Mac is not reachable from inside a container: a bind mount would work on this machine and
nowhere else, and on the Phase 12 server there is no such directory at all.

The second constraint is that **a run is only tracked if its artifacts are tracked too**. The
model file, the SHAP plots and the evaluation report are artifacts. If those live in a local
directory while the metrics live in a database, half of every run is machine-local.

## Options considered

| Option | Trade-off |
|---|---|
| **A. Local files (`mlruns/`)** | Nothing to run, nothing to configure. But the model registry is unavailable with a file store, Phase 8 cannot reach it from a container, and `mlruns/` is either committed (binary artifacts in git) or lost. |
| **B. SQLite + a local artifact directory** | The registry works. Still unreachable from a container, still machine-local artifacts, and SQLite has one writer - fine now, a trap the first time anything runs in parallel. |
| **C. A server in Docker Compose: Postgres backend, RustFS artifacts** | Reachable from any container by service name, the registry works, artifacts land in the same object store as every other layer of this project. Costs a container (~200 MB) and two one-off setup steps. |

## Decision

**Option C.** `mlflow` is a Compose service, built from `infra/mlflow/Dockerfile`:

- **Backend store:** a `mlflow` database in the existing Postgres instance. Its own database, not a
  schema in `drugwatch`: MLflow owns and migrates that schema, and it has no business sharing a
  database with the gold layer. Same reasoning as Superset's and Airflow's metadata databases.
- **Artifact store:** `s3://mlflow/` on RustFS, a fourth bucket beside `raw`, `bronze` and
  `silver`. Model files are exactly what an object store is for, and `rustfs-init` creates it, so
  recovery after `docker compose down -v` is the one command it already was.
- **`--serve-artifacts`:** clients send and fetch artifacts **through the server**, which is then
  the only component holding S3 credentials. The training code on the Mac and the Phase 8 container
  need `MLFLOW_TRACKING_URI` and nothing else. One fewer place for a key to leak, and Phase 12 gets
  one fewer secret to deploy.

Three things were found by building it rather than assumed:

- **The official image has neither a Postgres driver nor an S3 client.** `psycopg2` and `boto3` are
  both absent from `ghcr.io/mlflow/mlflow:v3.18.0`, so the server cannot reach either store as
  shipped. Same situation as Superset, same fix: a three-line Dockerfile pinning exactly those two.
- **RustFS needs path-style S3 addressing (ADR 0002), and boto3 has no environment variable for
  it.** `addressing_style` is read from the AWS config file only, so passing it as an environment
  variable would silently not apply. The setting is written into the image instead.
- **The image has no `ENTRYPOINT` and its `CMD` is `python3`**, so Compose's `command` arguments
  were handed to the Python interpreter (`"--host": executable file not found`). The entrypoint is
  named explicitly. Its healthcheck uses `python3` rather than `curl`, which the image also lacks -
  no package is installed for a healthcheck's sake.

**Port 5050 on the host, 5000 in the container**, because macOS runs AirPlay Receiver on 5000.

## Consequences

- Two one-off setup steps after a fresh clone or `docker compose down -v`:
  `CREATE DATABASE mlflow` and `docker compose run --rm rustfs-init`. Both are in CLAUDE.md §10
  beside the equivalents for Superset and Airflow.
- Docker's memory budget: MLflow idles at roughly 200 MB against the VM's 4.9 GB, which held ~0.7 GB
  before this. Airflow still runs on the host (ADR 0012), so nothing competes with Spark.
- **Verified end to end before any modelling was written** (`ml/src/drugwatch_ml/smoke_test.py`):
  a run is recorded with its git commit and data fingerprint, and an artifact is written to RustFS
  and read back byte for byte. That last check matters because `log_artifact` reports success
  whether or not the server can reach its artifact store - a misconfigured bucket would otherwise
  surface in Phase 8 as a model that cannot be loaded, long after the run that "succeeded".
  Confirmed independently against RustFS: `s3://mlflow/1/<run>/artifacts/smoke.json`.
- Phase 12 must put this behind the same hardening as Superset, or not expose it at all. MLflow has
  **no authentication here**, which is acceptable for a service bound to `127.0.0.1` and is not
  acceptable on a public server.
