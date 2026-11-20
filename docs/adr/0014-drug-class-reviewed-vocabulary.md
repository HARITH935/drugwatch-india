# ADR 0014 — `drug_class` comes from a reviewed vocabulary, held as a list per product

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decided by:** Harith (project owner) — decision B of Phase 6, taken 2026-11-19 and built out here
- **Affects:** `dim_drug` (§8.1), `mart_drug_class_failures` (§8.2), Phase 6 dashboard 3c,
  and §12's "share of reports by drug class" risk-model feature

---

## Context

The plan puts `drug_class` on `dim_drug` ("Antibiotic, Antidiabetic, Antihypertensive…", §8.1) and
builds `mart_drug_class_failures` on it (§8.2). Phase 4 shipped `dim_drug` **without** the column,
with the reason written into the model: **nothing in the CDSCO archive classifies a medicine.**
There is no ATC code, no therapeutic group, no BNF chapter — only the product name a manufacturer
printed on the pack. Measured on the real archive (7,126 findings over 5,651 distinct product
names, 2026-11-20):

- `generic_name` is filled for **1,340 of 5,651** product names (23.7%), and when it is filled it
  holds the whole printed string (`"Amoxycillin and Potassium Clavulanate Tablets IP"`), not a
  normalised salt. It is not a classification and cannot be turned into one.
- Product names do, however, usually lead with the active ingredient. A vocabulary of **215
  ingredient phrases** matches **5,746 of 7,126 findings (80.6%)**.
- **564 findings (7.9%) contain ingredients from more than one class** — up to four
  (`"Ambroxol Hydrochloride, Terbutaline Sulphate, Guaiphenesin & Menthol Syrup"`). Combination
  products are the norm in this archive, not the exception.
- **Not everything CDSCO tests is a medicine.** Absorbent cotton wool (50 findings), absorbent
  gauze, bandages, hypodermic syringes, hand sanitiser (41), soap, hair colour, mehandi cones and
  propylene glycol are all in it, tested against IP standards.

So the class cannot be read from the data. It has to come from outside it — which makes it **a
claim someone made**, not a fact the archive reports, and the design has to keep that distinction
visible instead of burying it in a column.

## Options considered

| Option | Trade-off |
|---|---|
| **A. Leave it out, as Phase 4 did** | Nothing is invented. But §8.2's mart and §12's feature stay unbuildable, and "what kinds of medicine get reported" is one of the questions the project exists to answer. |
| **B. Infer the class from name fragments in code** | No review burden, and it would look complete. But a regex deciding that `-statin` means lipid-lowering is a guess presented as a fact, and it fails silently: nobody ever sees the cases it got wrong. CLAUDE.md §5's "a missed merge is better than a wrong merge" applies to this exactly. |
| **C. Ingest a real classification source (ATC / CDSCO's own drug index)** | The honest ideal: a citable authority instead of a judgement. But it is a Phase 2–3-sized ingestion job — find a source whose licence allows public republication, download it under ADR 0003's anonymous-visitor rule, then match free-text Indian pack names to it, which is the same entity-resolution problem as manufacturers and harder. Not analytics work. |
| **D. A reviewed vocabulary of ingredient phrases, accepted by a person, as a list per product** | The ADR 0009 shape, which this archive has already been through once. Costs a review session and tops out around 80% coverage. Everything it does not cover stays `Unclassified` and is reported as a number, not hidden. |

## Decision

**Option D**, with three specifics that each exist to stop a particular falsehood.

**1. Phrases, never single words.** A word-level vocabulary files `"Atorvastatin Calcium Tablets
IP"` under mineral supplements, because `calcium` there is the salt the statin is formulated as.
So mineral and salt names appear only as complete phrases — `calcium carbonate`, `ferrous
sulphate`, `sodium chloride` — and a bare `calcium`, `sodium` or `sulphate` is never in the
vocabulary. Tested against `"Diclofenac Sodium"`, `"Thyroxine Sodium"` and `"Rabeprazole Sodium"`:
each matches only its active ingredient. The match is a whole-word match, so `ringer` does not
match `Ringerol` and `aspirin` does not match `Aspirinox`.

**2. A list per product, not one class.** With 7.9% of findings containing two to four classes,
picking one needs a priority rule that cannot be justified ("why does Antibiotic outrank
Probiotic?"). `drug_classes` is an array, a combination product is counted under each of its
classes, and **every chart built on it states that the classes therefore add to more than the
total** — the same contract as `failure_categories` (ADR 0009).

**3. Classes that say when something is not a medicine.** Four of the 26 classes exist for this:
`Surgical consumable or device`, `Antiseptic / disinfectant`, `Cosmetic or toiletry`,
`Pharmaceutical raw material`. Forcing cotton wool into a therapeutic class would be a plain
falsehood, and leaving it in `Unclassified` would make it look like a drug nobody could identify.
This matters most for the beauty creams: some were tested *because* they contained steroids they
should not have, so charting them under `Corticosteroid` would invert what the finding means.

**The review itself** (`analytics/src/drugwatch_analytics/drug_class_review.py`) splits the
proposals the way Phase 3's manufacturer review did:

- **187 `CLEAR`** entries — the class is the ingredient's textbook use and there was nothing to
  choose. Offered as one batch per class, with every ingredient's reason, its finding count and a
  real product name printed first. Reading 23 antibiotics is quicker than answering 23 questions
  and it is the same decision.
- **28 `JUDGEMENT`** entries — asked one at a time, each printing **why the proposal might be
  wrong** before asking. Aspirin is a painkiller at full dose and a clot preventer at the low dose
  used here. Menthol is a decongestant in a cough syrup and a skin coolant in a pain gel.
  Clavulanate is not an antibiotic at all. Soap may be a cosmetic or an antiseptic and the pack
  name rarely settles it. `n` is a real answer: rejecting an entry leaves those products
  `Unclassified`, which is the correct outcome when nobody can say.

Every proposal carries a written reason, and that is enforced rather than hoped for — one test
rejects a reason under 13 characters, another rejects a reason that only restates the ingredient
and the class it is proposed for (`"Vitamin."` under `Vitamin / mineral supplement`, `"Bandage."`
under `Surgical consumable or device`), and a third requires each judgement call to state its
alternative. A reason a reviewer cannot disagree with is decoration.

## Consequences

- `dim_drug` gains `drug_classes` (an array) and the marts unnest it. `mart_drug_class_failures`
  (§8.2) becomes buildable, and so does §12's "share of reports by drug class" feature.
- **Roughly a fifth of findings stay `Unclassified`**, and that number goes on the dashboard. It is
  mostly brand-named products whose pack prints no ingredient (`"Zylinta Syrup"`), which is a real
  limit of name-based classification, not a bug to be tuned away.
- **The vocabulary is committed to git, unlike the manufacturer-review decisions.** An ingredient's
  pharmacological class is published knowledge; the manufacturer mapping holds real CDSCO
  manufacturer names, which ADR 0003 keeps out of the repo. No count from the archive goes into the
  seed either — a measurement mixed into it would make the claim look like something CDSCO said.
- **Two implementations of one match rule**: Python (for the review, which has to run before any
  seed exists) and SQL (for dbt). A test compares them on every seed row against the live gold
  layer rather than trusting that they agree.
- This is **not** a drug classification anyone should cite. It is good enough to answer "what kinds
  of medicine appear in these alerts", which is what the dashboard asks. Option C remains the right
  answer if the project ever needs a defensible one, and nothing here blocks it: swapping the seed
  for an ingested source changes one table.
