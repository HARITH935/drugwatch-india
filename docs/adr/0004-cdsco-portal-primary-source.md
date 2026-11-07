# ADR 0004 — CDSCO NSQ portal is the primary source

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** Harith (project owner)
- **Changes:** plan §1 / §5 assumption that CDSCO's monthly PDFs are the main data source
- **Details:** `docs/data-sources.md` §1

---

## Context

The plan was built on CDSCO's monthly NSQ / spurious alert PDFs. Phase 1 step 1 found that:

- **The PDFs stopped.** On 2025-08-28 CDSCO announced NSQ alerts had moved to a "new link". The last monthly
  PDFs are for Jun 2025.
- **PDF coverage is patchy:**
  - central labs: 11 scattered months 2017–2023, then Apr–Jul 2024 and Jan–Jun 2025;
  - state labs: May–Jul 2024 and Jan–Jun 2025;
  - Aug–Dec 2024 is missing from the listing (at least one of those files exists on the server).
- **The new link is a portal** (`cdscoonline.gov.in/CDSCO/viewPublicNSQDrug`) with JSON endpoints and named
  fields (batch, product, brand, dates, manufacturer, result, lab, month). It covers **Jan 2019 – Sep 2026**
  for NSQ and 2025–2026 for spurious. Sampled months returned real rows (Jan-2019: 45, Sep-2026: 330).

## Options considered

| Option | Trade-off |
|---|---|
| **A. Portal primary, PDFs kept** | Complete and structured from 2019; the PDFs still give 2017–2018 history and Phase 2's extraction work. Overlap months become a free answer key for PDF extraction. |
| B. PDFs primary (as planned) | Matches the plan, but has big gaps and nothing after Jun 2025. The portal would be needed for recent months anyway. |

## Decision

**Option A.**
- Download **both** sources into `raw/`.
- The **portal JSON is the primary source from Jan 2019 onwards**.
- The **PDFs** cover 2017–2018 (and anything the portal lacks) and stay the input to Phase 2 extraction.
- Months covered by both are used to **measure** PDF extraction accuracy.

## Consequences

- **Downloader (Phase 1 step 4)** handles two kinds of source:
  - the PDF listing, with its two-hop `.jsp` → iframe → PDF download;
  - month-by-month portal JSON (`filteredNsqDrugTable?month=Mon-YYYY&source=All`, plus the spurious equivalent).
- **Raw portal responses are stored byte-for-byte.** They are Windows-1252 (cp1252), not UTF-8. `raw/` is never
  modified; decoding happens when building bronze.
- **Provenance for portal rows** is the request URL with its parameters, the download time and the response hash.
  These rows have no page or row index, and `extraction_method` (plan §8.1, CLAUDE.md §5) needs a new value
  such as `api`. That schema change is made in Phase 2/3, not now.
- **Phase 2 still runs** on the PDFs. How portal rows relate to the labelled eval set is decided at Phase 2.
  The eval-set rules in CLAUDE.md §5 still apply: the test split is never used for training or tuning.
- **Phase 10 (LLM extraction)** still targets hard PDF rows, but now covers a smaller share of the data.
- **"Link to the original CDSCO document"** (CLAUDE.md §6): portal rows have no per-row document. They link to
  the portal page plus the alert month. Settled in Phase 11.
- **Risk:** the portal is a single point of failure, and CDSCO has already changed format once (2025). The
  downloader checks the response shape and fails loudly if it changes.
- **Interview angle:** "The source I planned around turned out to have been replaced mid-2025. I found the new
  structured feed by tracing the portal's own JavaScript, made it the primary source, and turned the old
  PDFs into a measurable extraction benchmark instead of throwing that work away."

## Update (2026-11-07, Phase 1 step 6)

Looking inside the PDFs showed that the 2017–2023 "central NSQ" PDFs are **vaccine-only** one-page lists. Full drug
NSQ lists in PDF begin in Apr 2024, and the portal also holds the vaccine rows (two batches checked). This strengthens
the decision: the portal is the primary source; the PDFs add unique history only before 2019 (six vaccine lists, two
full drug lists from 2018, the bulk vaccine file), and Phase 2's extraction benchmark is the Apr 2024 – Jun 2025 PDFs.
Details: `docs/data-sources.md` §7.1.
