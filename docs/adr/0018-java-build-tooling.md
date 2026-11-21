# ADR 0018 — Java build tooling: Maven, Spotless and ArchUnit (and no coverage gate)

- **Status:** Accepted
- **Date:** 2026-11-21
- **Decided by:** Harith (project owner)
- **Affects:** `backend/` (Phase 9), and Phase 11's frontend only in that CI gains a second job

---

## Context

Phase 9 is the project's first Java. ADR 0005 settled the Python equivalent — uv for environments
and a lockfile, pytest, ruff in CI — and the same three questions have to be answered again for
Java, because the plan's §6 names Spring Boot and JUnit and stops there.

The questions are: which build tool, what keeps the code formatted, and what stops the layering
from decaying. The third matters more here than it did in Python: the plan asks for a *layered*
structure (controller → service → repository), and a layer boundary that only exists in a
documentation file stops existing the first time somebody is in a hurry.

## Decision

**Maven**, already installed at 3.10.0. The plan does not name a build tool. Gradle is the other
real option and is faster on large builds; Maven is chosen because its `pom.xml` is declarative
and readable top to bottom, because every Spring Boot example in the world is written for it, and
because "I can explain every line of this build file" is a Phase-9 requirement (CLAUDE.md §2) in a
way that build speed on one module is not.

**Spring Boot 4.2.0 on Java 21.** Both are the current releases, and the version was taken from
Maven Central's own `maven-metadata.xml` rather than from its search API, which answered **3.5.3**
— a whole major version stale. The same class of error as the `boto3==1.41.9` pin in Phase 7 that
never existed: a plausible version number is not a checked one.

**Spotless** for formatting, run in CI as a check. The direct equivalent of `ruff format --check`:
formatting arguments cost review attention and settle nothing.

**ArchUnit**, test-only, to enforce the layering as a test rather than as a convention:

- a controller may not call a repository directly;
- a repository may not depend on a controller or a service;
- entity and repository types stay package-private where the module does not publish them.

This is the Java version of the same instinct as `assert_drug_classes_never_invent_a_class` or the
test that reads `docker-compose.yml` to check the risk service has no database credentials: a rule
with nothing checking it is a comment.

## What is deliberately left out

**No JaCoCo coverage gate**, which the Spring Boot skill's reference configuration suggests at 80%.

A coverage percentage measures which lines were executed, not which behaviours were checked. A
test that calls every getter clears the gate; the tests that have actually paid for themselves in
this project would mostly not have moved it — the one asserting that SHAP contributions reconstruct
the prediction, the one proving a row-level bootstrap gives a falsely narrow interval, the one that
caught `filter (where drug_class = 'Unclassified')` counting zero of 1,382 findings. None of those
is about line coverage, and a team optimising for the number writes the other kind.

Coverage is still worth *looking* at, so JaCoCo may be added as a report with no threshold if it
earns its place. What is rejected is a build that fails on a percentage.

## Consequences

- CI gains a `backend` job: `mvn verify` plus `spotless:check`. It is slower than the Python lint
  job — a Spring context and real containers — so it runs in parallel rather than in sequence.
- Testcontainers (plan §6) means Docker is required to run the backend tests, locally and in CI.
  That is already true of every other phase's integration tests.
- `backend/` holds a `.mvn/wrapper` so the build pins its own Maven version, the way `uv.lock` pins
  Python's dependencies. A build that silently uses whatever Maven is on the machine is the same
  problem `--frozen` solved for the serving image in ADR 0017.
