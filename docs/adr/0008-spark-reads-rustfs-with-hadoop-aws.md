# ADR 0008 — Spark reads and writes RustFS through the hadoop-aws (S3A) connector

- **Status:** Accepted
- **Date:** 2026-11-12
- **Decided by:** Harith (project owner)
- **Affects:** `spark/pyproject.toml`, `spark/src/drugwatch_spark/session.py`, `spark/src/drugwatch_spark/prefetch.py`

---

## Context

Phase 3 cleans bronze into silver with PySpark (plan §6, §9). Bronze and silver live in RustFS, an S3-compatible
store (ADR 0002), and the plan's architecture (§7) has Spark reading and writing those buckets directly. PySpark ships
without any S3 support. Hadoop's S3 connector, **`hadoop-aws`** ("S3A", paths like `s3a://bronze/...`), adds it, but
it isn't in the approved stack, and it needs Amazon's **AWS SDK v2 `bundle`**: a single 686 MB jar.

Versions are locked together: PySpark 4.2.1 is built with **Hadoop 3.5.0**, so the connector must be
`hadoop-aws:3.5.0`, which declares AWS SDK bundle 2.35.4. A mismatched pair fails at runtime with missing-class errors.

## Options considered

| Option | Trade-off |
|---|---|
| **A. hadoop-aws connector** | Spark reads and writes the lake directly, as drawn in the plan and as Airflow will run it (Phase 5). Standard setup, worth knowing. Cost: a one-time 686 MB download (cached by Spark in `~/.ivy2*`), plus a few S3A settings. |
| B. Copy to local disk first | No new library: boto3 copies bronze (about 1 MB) to a git-ignored folder; Spark works on local files; silver is uploaded afterwards. Lighter, but Spark never touches the lake, and every later pipeline needs the copy steps. |

## Decision

**Option A.**

- **PySpark 4.2.1**, a patch release (4.3.0 was 13 days old when this was decided). The `spark/` project pins
  `pyspark>=4.2.1,<4.3`, because a minor upgrade can change the Hadoop version.
- **`spark.jars.packages = org.apache.hadoop:hadoop-aws:3.5.0`**: Spark downloads it and the SDK bundle from Maven
  Central on the first run that needs S3. A test starts Spark and fails if the Hadoop version Spark is built with
  ever stops matching the connector version.
- **S3A settings** (`session.py`): the endpoint and keys come from `.env` (`RUSTFS_ENDPOINT`, `RUSTFS_ACCESS_KEY`,
  `RUSTFS_SECRET_KEY`), with `RUSTFS_ENDPOINT` defaulting to `http://localhost:9000` exactly as
  `RawStore.from_env()` already does (`ingestion/.../store.py`), since `.env` itself never sets it; **path-style
  addressing** (ADR 0002); TLS only when the endpoint is `https`; a fixed region (`us-east-1`), because SDK v2
  insists on one and RustFS ignores it. Spark hides values whose name contains "secret" in its logs and UI.
- **Only S3-reading code needs the connector.** Unit tests build small tables in memory or on local disk, so CI never
  downloads the 686 MB bundle; reading the real lake is a local integration test.
- **On a slow or unstable connection, prefetch the SDK bundle separately** (`prefetch.py`): it downloads the jar in
  4 parallel, independently resumable pieces (each retries up to 20 times with backoff, picking up where it left
  off) and checks the joined file's SHA-256 against the one Maven Central publishes before keeping it. This matters
  because Spark's own Ivy resolver downloads a package as one unresumed stream, which can fail repeatedly on a link
  that drops mid-transfer. Spark/Ivy checks `~/.m2/repository` (the "local-m2-cache" resolver) before Maven Central,
  so once prefetched there, Spark's own resolution finds it immediately and downloads only the small remaining jars
  (`hadoop-aws`, `wildfly-openssl`, `analyticsaccelerator-s3`: well under 1 MB combined).
- **CI needs an explicit JDK.** GitHub's `ubuntu-latest` runners ship several JDKs but don't guarantee which one is
  on `PATH` by default, and Spark 4.x requires Java 17+; the `spark` matrix entry in `lint.yml` installs Temurin 17
  explicitly (`actions/setup-java`) rather than relying on an unverified default.

## Consequences

- First S3 run on a new machine: a one-time download of about 700 MB (needs internet; cached afterwards; `prefetch.py`
  makes the large part of it resumable).
- Upgrading PySpark means checking its Hadoop version and moving `hadoop-aws` with it (the version test fails
  otherwise).
- **Confirmed working, 2026-11-12:** a real run against RustFS read all 1,317 PDF bronze rows (44 files) and all
  7,005 portal bronze rows (108 files), matching the counts recorded in Phase 2 and Phase 3 step 0 exactly; the SDK
  bundle was served from `local-m2-cache` as designed, with no 686 MB re-download.
- **Interview angle:** "Spark has no S3 support built in. I added Hadoop's S3A connector matched to Spark's Hadoop
  version, configured it for a self-hosted S3-compatible store (path-style, custom endpoint, keys from the
  environment), and kept the 686 MB SDK out of CI by testing transformations on local data. On a slow home
  connection, a single-stream 686 MB download kept failing partway through, so I wrote a small resumable,
  checksum-verified downloader that primes Maven's local cache before Spark ever asks for it."
