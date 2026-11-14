# ADR 0009 — Failure categories: a wider vocabulary, held as a list per row

- **Status:** Accepted
- **Date:** 2026-11-13
- **Decided by:** Harith (project owner)
- **Affects:** `spark/src/drugwatch_spark/failure_category.py`, Phase 3 step 6, and every later count built on it
  (Phase 4 marts, Phase 6 dashboards, Phase 7 risk-score features)

---

## Context

Phase 3 step 6 says: *"Map failure reasons into standard categories (Assay, Dissolution, Sterility, Description,
Particulate, Spurious, Other)."* That is seven categories, implying one per row.

`failure_reason` is free text written by whichever government lab tested the sample. Measured on the real archive
(8,322 silver rows, 8,317 with a reason, 2026-11-13):

- **3,730 distinct values** after collapsing case and whitespace. The 800 most common cover only **61.5%** of rows,
  so a value-to-category lookup table cannot work; the category has to be read from the text.
- Values range from a bare `"Dissolution"` to 994-character sentences
  (`"The sample does not conform to I.P. w.r.to the tests for Dissolution"`), with the same test written many ways.
- **1,833 rows (22.0%) name more than one failed test** — `"Dissolution and Assay"`,
  `"ph, particulate matter and description"`, up to seven tests in one row.
- The plan's seven categories leave **17.5% of rows in "Other"**, and that residue is not noise: it contains every
  pH (368 rows), Content (153), Related Substances (229), Uniformity (300), Water (161), Identification (462) and
  Disintegration (303) failure. "Other" would be the second-largest slice on a dashboard and would tell a reader
  nothing.

## Options considered

| Option | Trade-off |
|---|---|
| **A. The plan's 7, one per row** | Exactly as written; simplest. But 17.5% in "Other", and a row failing two tests loses one of them to a priority rule that is hard to defend ("why does Assay outrank Dissolution?"). |
| **B. The plan's 7, as a list** | Keeps multi-test rows honest, still 17.5% "Other". |
| **C. A wider vocabulary, as a list** | 14 test categories + Spurious + Other, each one added only because real rows report it. "Other" falls to **3.0%**, and a row failing two tests is counted under both. Cost: more patterns to maintain and explain, and Phase 4 must unnest an array to count by category. |

## Decision

**Option C.** `failure_categories` is an **array**, and the vocabulary is:

| Category | Rows | % | Category | Rows | % |
|---|---|---|---|---|---|
| Assay (incl. Content) | 3,365 | 40.4% | Uniformity | 300 | 3.6% |
| Dissolution | 2,238 | 26.9% | Labelling | 287 | 3.4% |
| Description | 1,333 | 16.0% | Other | 255 | 3.1% |
| Sterility | 577 | 6.9% | Physical | 244 | 2.9% |
| Particulate | 535 | 6.4% | Related substances | 229 | 2.8% |
| Identification | 462 | 5.6% | Water | 161 | 1.9% |
| pH | 368 | 4.4% | Spurious | 77 | 0.9% |
| Disintegration | 303 | 3.6% | | | |

Supporting decisions, each made against the real values:

- **"Content" counts as Assay.** An assay *is* a content determination and CDSCO writes both for the same finding
  (`"assay/content of cholecalciferol"` appears as one phrase). But `water content`, `moisture content` and
  `uniformity of content` are other tests and are excluded from Assay by name.
- **Spurious comes from `is_spurious`, never from the text.** The word "spurious" appears in the reason text of
  ordinary NSQ rows — one real value ends `"...the tests for identification and assay spurious"` — so matching the
  word would mark **264 rows** spurious when only **77** are. A spurious row still keeps its lab-test categories:
  those tests were really run, on the seized counterfeit sample.
- **"Misbranded" is Labelling, not Spurious.** Misbranding means the label was wrong or incomplete. Filing it under
  Spurious would accuse a manufacturer of counterfeiting, which CLAUDE.md §6 forbids.
- **Labelling is an allow-list of real phrasings, not the word "label".** In this archive "label" usually means the
  **declared strength**, not the printed label: `"does not conform to label claim with respect to the content of
  ketoconazole"` (105 rows), `"...34.85% of the labelled amount"` (42), `"conform to label with respect to the
  content of available iodine"`, `"against labelled claim of 2500 mg per ml"` — all strength shortfalls, already
  counted under Assay. A bare `\blabel` pattern reported **390** labelling offences against the **287** the
  allow-list finds: **103 rows (26%) were strength shortfalls recorded as labelling offences.** Carving out each
  phrasing one at a time only moved the goalposts, so the pattern was inverted to list what CDSCO actually writes
  for a labelling offence (`misbranded`, `incorrect labelling`, `label review`, `on the label`, `product label`,
  `label of the container`, `labelled as`, `not printed on`, `printed on the strip`).
- **Disintegration is its own category, not part of Dissolution.** Different test (the tablet breaking up, versus
  the drug going into solution) and reported alone in 303 rows.
- **Every pattern is bounded** (`\b…\b` / `(?!\w)`). `bet` (the Bacterial Endotoxin Test, 9 rows) would otherwise
  match "diabetes" and "betamethasone"; `ph` would match "graph" and "morphine".
- **CDSCO's own misspellings are matched as spelled**, not corrected: `misbrandad` (13 rows), `sterillity` (6),
  `alochol` (6), `susbtances` (3), `uniformaly` (3), `appeareance` (2). A typo in the source is not a reason to
  lose the row's category.
- **A reason naming no test gets `Other`**, the same as an unrecognised one: `"nsq"` (10), `"not applicable"` (7),
  `"does not conform to i.p."` (17), `"not of standard quality"` (3) all mean "we cannot say which test failed".
  A row with **no reason at all** gets an **empty list**, which is a different fact and stays distinguishable —
  though no row in this archive ends up empty: the only 5 rows without a reason are spurious-document rows, so
  they come out as `["Spurious"]`.

## Consequences

- **"Other" is 3.1%** (255 rows). What is left is mostly genuinely unspecified prose, plus small one-off groups
  deliberately not chased: `grade and germicidal value`, `storage does not comply`, `adulterated`,
  `in test of lactic acid per mg of ciprofloxacin` (2 rows each). Adding a pattern per sentence would make the
  rules unexplainable, which costs more than it gains.
- **Counts by category do not sum to the row count**, by design: 1,833 rows are in two or more categories. Every
  chart built on this must say "rows reporting each test", not "share of rows".
- Some rows carry a defensible extra category: a misbranding row about a colour name also matches Description
  (8 rows), and `uniformity of volume` matches both Uniformity and Physical (5 rows).
- Phase 4's dbt models must **unnest** `failure_categories` (one row per category) before grouping, and step 8's GE
  suite should assert every value is in this vocabulary and watch the "Other" share for drift when CDSCO's wording
  changes.
- **Interview angle:** "The plan named seven categories. The data had 3,730 distinct free-text reasons, 22% of
  rows naming more than one failed test, and seven categories left 17.5% in 'Other' — so I measured first, widened
  the vocabulary to what the labs actually report, and made the column a list. The subtle part was false positives:
  in CDSCO's wording 'label claim' and 'labelled amount' mean a strength shortfall, not a mislabelled pack, and
  matching the word 'label' overstated labelling offences by 36% (390 against 287). I found that by auditing what
  every pattern actually matched, not by trusting the coverage number — and because mislabelling is an
  accusation, I inverted that one rule into an allow-list of the phrasings CDSCO really uses."
