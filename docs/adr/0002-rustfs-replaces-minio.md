# ADR 0002 — RustFS replaces MinIO

- **Status:** Accepted
- **Date:** 2026-11-03
- **Decided by:** Harith (project owner)
- **Supersedes:** the "Data lake: MinIO" row of ADR 0001

---

## Context

The plan used MinIO as the S3-compatible data lake for the `raw`, `bronze` and `silver` layers. While
writing `docker-compose.yml` in Phase 0, we found MinIO's free community edition is no longer usable as
a container:

- `docker pull minio/minio` has no image to pull: the Docker Hub repository returns HTTP 404 (checked 2026-11-03).
- The community edition is now distributed as source code only, and its GitHub repository says it is no
  longer maintained. Any old pinned image will get no further security fixes.

DrugWatch only talks to storage through the standard **S3 API**, so any S3-compatible server works
without changing the design.

## Options considered

| Option | Status on 2026-11-03 | Licence | Trade-off |
|---|---|---|---|
| **RustFS** (`rustfs/rustfs`) | v1.0.4 released 2026-10-25, ~20M Docker pulls | Apache 2.0 | Actively maintained, built as a MinIO drop-in. A younger project (recently reached 1.0). |
| MinIO community fork (`pgsty/minio`) | Last release 2026-08-04, ~3M pulls | AGPL | No renames needed, but a small community project reportedly rebranding as "Silo". |
| MinIO AIStor Free (official) | Current | Proprietary, single-node only | Needs a sign-up license file mounted in every environment, including CI. |

## Decision

Use **RustFS**, pinned to `rustfs/rustfs:1.0.4`, everywhere the plan said MinIO.

## Consequences

- **Docs renamed** MinIO → RustFS (plan, CLAUDE.md, README, PROGRESS). The bucket layout (`raw`,
  `bronze`, `silver`) is unchanged.
- **Credentials:** `RUSTFS_ACCESS_KEY` and `RUSTFS_SECRET_KEY`. If they're missing, RustFS falls back to
  a public default (`rustfsadmin`), so `docker-compose.yml` uses `${VAR:?}` to refuse to start without them.
- **Path-style addressing:** by default RustFS only understands S3 URLs shaped `host/bucket/key`. Every S3
  client must be configured for it, e.g. boto3 `Config(s3={"addressing_style": "path"})`, Spark
  `fs.s3a.path.style.access=true`.
- **Ports:** S3 API on 9000; the web console is on 9001 at `/rustfs/console/` (the bare root URL returns 403).
- **Health check:** the image has no built-in one; we use `curl http://localhost:9000/health`.
- **Risk:** RustFS is younger than MinIO. Raw files are the source of truth, so the Phase 12 backups matter.
- **Interview angle:** "A core dependency was discontinued mid-project. I compared three options on
  maintenance, licence and migration cost, and switched without touching the design because we'd coded
  against the S3 API, not a vendor."

## References

- MinIO repository README (community edition source-only / no longer maintained): https://github.com/minio/minio
- RustFS image: https://hub.docker.com/r/rustfs/rustfs
