# ADR 0005 — Python tooling: requests, boto3, uv, pytest, ruff

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** Harith (project owner)
- **Adds to:** plan §6.1 (Approved Additions)

---

## Context

Phase 1 step 4 is the first Python code: a downloader that fetches files from CDSCO, NPPA and Jan Aushadhi
and stores them in RustFS's `raw` bucket. The locked stack (plan §6) names Python, but no HTTP client, S3
client, environment manager, test runner or linter. CI also has no Python lint yet: Phase 0 deferred it
until Python first appeared.

## Options considered

| Need | Chosen | Alternative | Trade-off |
|---|---|---|---|
| HTTP client | **requests** | httpx | requests is the most common Python HTTP library. httpx adds async and HTTP/2, which buy nothing at one request per 3 s per host (ADR 0003). Retries are a short loop of our own (see Consequences), so no retry library is needed. |
| S3 client | **boto3** | minio SDK | boto3 is the standard S3 SDK, and Airflow's AWS provider (Phase 5) is built on it. It's large and verbose. The minio SDK is smaller but tied to the vendor ADR 0002 moved away from. |
| Environment + dependencies | **uv** | pip + venv | uv creates the virtualenv, installs packages and writes a lockfile (`uv.lock`), so local and CI install identical versions. pip has no lockfile by default. uv is newer and less familiar. |
| Tests | **pytest** | unittest (stdlib) | pytest is the standard: plain `assert`, fixtures, clear failure output. unittest needs class boilerplate. |
| Lint + format | **ruff** | flake8 + black (+ isort) | One fast tool that replaces three, configured once at the repo root. |

## Decision

Adopt all five, as chosen above.

- **Layout:** each Python folder gets its own uv project (`pyproject.toml` + `uv.lock`). Starting with
  `ingestion/`. Separate projects keep heavy, conflicting dependencies (Spark, Airflow, PyTorch) apart.
- **Shared lint rules:** one `ruff.toml` at the repo root applies to every Python folder.
- **Python version:** 3.13 everywhere (`.python-version` and `requires-python >= 3.13`).
- **CI:** a `python` job in `.github/workflows/lint.yml` runs `ruff check`, `ruff format --check` and
  `pytest` using the versions pinned in `uv.lock`.

## Consequences

- New contributors need only `uv`; `uv sync` creates `.venv/` and installs everything.
- `uv.lock` is committed and CI installs with `--locked`, so it fails if `pyproject.toml` and the lockfile
  disagree.
- Later Python folders (`extraction/`, `spark/`, `ml/`, `ml-serving/`, `llm/`) follow the same pattern and
  get added to the CI job when they appear.
- boto3 must always be configured for path-style addressing with RustFS (ADR 0002).
- **Retries are hand-written, not urllib3's `Retry`** (amended in step 4b). urllib3 retries the first failure
  with no delay and bypasses our per-host limiter, so one server error would trigger an instant second
  request and break the 3-second rule. Our loop (`fetcher.py`) sends every attempt through the limiter.
- **Interview angle:** "I picked boring, standard tools where the problem was ordinary: requests for HTTP,
  boto3 for S3. I used a lockfile so CI and my laptop could never drift. Every library was approved and
  recorded before it entered the codebase."

## References

- requests: https://requests.readthedocs.io · urllib3 Retry: https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html
- boto3: https://boto3.amazonaws.com/v1/documentation/api/latest/index.html
- uv: https://docs.astral.sh/uv/ · ruff: https://docs.astral.sh/ruff/ · pytest: https://docs.pytest.org
