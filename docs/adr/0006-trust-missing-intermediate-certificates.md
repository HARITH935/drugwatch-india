# ADR 0006 — Supply missing intermediate certificates; never turn verification off

- **Status:** Accepted
- **Date:** 2026-11-05
- **Decided by:** Harith (project owner)
- **Affects:** `ingestion/src/drugwatch_ingestion/fetcher.py`, `ingestion/src/drugwatch_ingestion/certs/`

---

## Context

The first request to `nppa.gov.in` failed with `CERTIFICATE_VERIFY_FAILED: unable to get local issuer
certificate`. `openssl s_client` showed why: the server sends only its own certificate (`CN=nppa.gov.in`)
and leaves out the intermediate that links it to a trusted root, *Sectigo Public Server Authentication
CA DV R36*. Browsers hide this mistake by downloading the missing intermediate themselves, from the
"CA Issuers" address inside the certificate. Python (requests + certifi) doesn't.

The failure also showed a flaw in the fetcher: it retried the certificate error 4 times (35 s of
backoff), although a certificate problem never fixes itself.

## Options considered

| Option | Trade-off |
|---|---|
| **A. Supply the missing intermediate** | Checks stay fully on. Works on the Mac, in CI and in Linux containers (Airflow). A committed file to maintain: if NPPA's renewed certificate (current one expires 2026-11-18) uses a different intermediate, downloads fail loudly and we add that one. |
| B. Use the OS trust store (`truststore` library) | macOS fetches missing intermediates, so it works locally. Linux CI and Airflow containers don't, so it fails there the same way. New dependency. |
| C. Manual drop for all NPPA files | No code change, but about 170 files by hand, and again for every new order. |
| Turn verification off (`verify=False`) | **Rejected outright.** Anyone on the network path could impersonate NPPA and feed us fake prices. |

## Decision

**Option A.**

- The intermediate is fetched once from the address in NPPA's own certificate
  (`http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt`). Before committing it we
  checked two things:
  1. it is signed by a root already in certifi (`openssl verify -CAfile <certifi> …` → `OK`);
  2. NPPA's chain verifies with it supplied (`Verify return code: 0`).
- It is committed as a public `.pem` in `ingestion/src/drugwatch_ingestion/certs/`, with a header giving
  its subject, issuer, validity, SHA-256 fingerprint, source and the command to re-check it.
- `PoliteFetcher` mounts a transport adapter for `https://`. The adapter's SSL context has requests'
  default TLS settings and certifi's roots, **plus** every `.pem` in `certs/`. Verification and hostname
  checks stay on, and tests fail if either is ever switched off.
- **Certificate errors are never retried** (`requests.exceptions.SSLError` → `FetchError` at once).

**Why this adds no new trust:** an intermediate is only accepted because a root we already trust signed
it. Supplying it gives the client the link the server forgot. Any certificate it signs would be trusted
anyway if the server sent the chain correctly.

## Consequences

- Any future source with the same misconfiguration is fixed the same way: verify the intermediate
  against certifi, add its `.pem` with a header, record it here.
- **Watch 2026-11-18:** NPPA's certificate expires then. If the renewed one chains through a different
  intermediate, NPPA downloads fail with a clear TLS error until that intermediate is added.
- **Interview angle:** "A government site had a broken certificate chain. The quick fix everyone
  copies from Stack Overflow is `verify=False`. Instead I diagnosed it with openssl, supplied the
  missing intermediate after verifying it against the trusted roots, and stopped the fetcher retrying
  errors that can't fix themselves."
