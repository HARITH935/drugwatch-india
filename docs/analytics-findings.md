# What the gold layer actually shows

Phase 6 step 1. Produced by `analytics/notebooks/01-explore-gold.ipynb` against the gold layer on
**2026-11-19** (7,126 findings, 101 published alert months, 2019-01 … 2026-09 plus a thin PDF-only
2017–18 tail).

Only aggregates are recorded here. The notebook is committed with its outputs cleared, because a
notebook's output is real CDSCO rows and those stay out of this repo (ADR 0003, ADR 0013).

---

## 1. The rising line is testing effort, not falling quality

This is the finding that constrains every other chart.

| Year | Findings | Distinct reporting labs | Months published | Findings per published month |
|---|---:|---:|---:|---:|
| 2017 | 2 | 1 | 2 | 1.0 |
| 2018 | 82 | 2 | 6 | 13.7 |
| 2019 | 404 | 25 | 12 | 33.7 |
| 2020 | 314 | 5 | 12 | 26.2 |
| 2021 | 344 | 7 | 12 | 28.7 |
| 2022 | 574 | 9 | 12 | 47.8 |
| 2023 | 642 | 9 | 12 | 53.5 |
| 2024 | 904 | 41 | 12 | 75.3 |
| 2025 | 1,959 | 168 | 12 | 163.3 |
| 2026 | 1,901 | 166 | 9 | 211.2 |

**Findings and the number of reporting laboratories correlate at r = 0.964 across years.** Findings
rose roughly 5x from 2019 to 2025; the number of laboratories named in those alerts rose nearly 7x.

A chart of "NSQ findings per month" will be read as "medicine is getting worse". On this evidence
that reading is unsupported: what grew fastest is **surveillance**. The model's own stated
limitation (plan §12) is the same point — these are *reported* failures from a non-random sample.

**Consequence for the dashboards:** any time series must carry the reporting-lab count beside it, or
a note that it measures reporting, not quality. A findings line on its own is misleading.

## 2. The archive is a long tail, not a league table

Of 2,609 manufacturers carrying 6,998 attributable findings (mean 2.7, **median 1**):

- **1,521 companies (58%) appear exactly once.**
- Top 1% of companies (26) hold **13.5%** of findings.
- Top 5% (130) hold **33.7%**; top 10% (260) hold **45.9%**.

**Consequence:** a "top 10 manufacturers" bar chart describes 10 companies out of 2,609 and says
nothing about the other 2,599 — while inviting exactly the verdict CLAUDE.md §6 forbids. If such a
chart is shown it must be ranked by **separate alert months** (a pattern that persisted), labelled as
a count of reports, and sit next to the distribution above so the reader sees the tail.

## 3. Failure categories: mentions, never shares of findings

| Category | Mentions | Manufacturers |
|---|---:|---:|
| Assay | 2,928 | 1,424 |
| Dissolution | 1,926 | 849 |
| Description | 1,106 | 588 |
| Sterility | 464 | 241 |
| Particulate | 434 | 229 |
| Identification | 399 | 236 |
| pH | 299 | 184 |
| Disintegration | 273 | 215 |
| Uniformity | 251 | 189 |
| Labelling | 236 | 178 |
| Other | 218 | 172 |
| Physical | 201 | 132 |
| Related substances | 200 | 135 |
| Water | 136 | 94 |
| **Spurious** | **77** | **0** |

21.8% of findings name more than one failed test (mean 1.28 categories), so **these do not sum to
7,126 and a pie chart would be wrong**. Axis labels must say "mentions".

**`Spurious: 77 mentions, 0 manufacturers` is the ethics invariant visible in the data itself** — a
counterfeit pack names the copied brand, so Phase 3 and Phase 4 attribute it to nobody.

## 4. The two state questions are almost never the same question

| State | Made here | Tested here | Of which by a state lab |
|---|---:|---:|---:|
| Himachal Pradesh | 2,147 | 104 | 76 |
| Uttarakhand | 878 | 62 | 43 |
| Gujarat | 433 | 73 | 72 |
| Madhya Pradesh | 368 | 67 | 28 |
| Maharashtra | 201 | 513 | 137 |
| Tamil Nadu | 114 | 570 | 501 |
| **West Bengal** | **103** | **1,758** | **29** |

**Where both states are known, they differ in 4,999 of 5,391 findings — 92.7%.** West Bengal tests
17x what it makes (CDL Kolkata draws nationwide); Himachal Pradesh makes 21x what it tests.

**Consequence:** "reports by state" must never be one chart, one map, or one number. Two charts,
labelled *made here* and *tested here*, that cannot be summed — and the manufacturing one is the only
one that says anything about where medicines come from.

## 5. Medicines, and the spurious slice

Tablet 3,697 · Injection 966 · **not stated 771** · Capsule 453 · Syrup 445 · Suspension 303 · the
rest under 120 each. The 771 unknown dosage forms are a disclosure, not a rounding error.

Spurious findings: **77 total, 0 attributed to a manufacturer, 17 carry the name printed on the fake
pack**, spanning 2024-04 … 2026-09 only. They are a separate phenomenon from quality failures and
belong on their own view, never mixed into a manufacturer ranking.

## 6. The gaps a public dashboard must disclose

| Gap | Size |
|---|---|
| Published alert months | **101 of 111** calendar months spanned — 10 months have no alert at all |
| Findings with no manufacturer named | 128 (77 spurious + 51 CDSCO never named one) |
| Manufacturers with no resolvable state | 603 of 2,609 (23%) |
| Findings missing a manufacture or expiry date | 158 |
| Pre-portal era (PDF only, 2017–18) | 132 findings — **1.9%** of the archive |

Sources behind the archive:

| Source | Method | Findings | Range |
|---|---|---:|---|
| portal NSQ | api | 6,917 | 2019-01 … 2026-09 |
| combined PDF | rule | 77 | 2018-05 … 2018-08 |
| portal spurious | api | 49 | 2025-06 … 2026-09 |
| spurious PDF | rule | 28 | 2024-04 … 2025-06 |
| state NSQ PDF | rule | 30 | 2024-05 … 2025-06 |

**"Not found" never means "guaranteed safe"** (CLAUDE.md §6), and these numbers are why: a batch can
be absent because it was never sampled, because its month was never published, or because it predates
the portal.

---

## What this means for the four dashboards

1. **Manufacturer trends** — rank by separate alert months, never by a score; show the long tail from
   §2 alongside; neutral wording throughout ("NSQ batches reported").
2. **States** — two charts, never summed, never one map; §4 is the reason, and the legal sensitivity
   of India's boundaries is a second one.
3. **Time** — never a bare findings line: pair it with the reporting-lab count from §1.
4. **Spurious** — its own view, unattributed, with the copied-name caveat stated.
5. **Every dashboard** — "Not medical advice. Data from CDSCO public alerts.", the batch number, the
   alert month, a link to the CDSCO document, the gaps from §6, and the freshness line from
   `ops.pipeline_run`.

**Still blocked:** a drug-class view needs the `drug_class` decision (no source in the archive), and
the price-gap view needs price data that does not exist downstream of `raw/` yet.
