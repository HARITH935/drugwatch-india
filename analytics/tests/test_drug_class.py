"""The drug-class vocabulary and its match rule (Phase 6 step 3c, ADR 0014).

The tests that matter here are the ones that pin down what the vocabulary must NOT do: file a
statin as a mineral supplement, let a proposal through without a reason, or quietly accept an
entry nobody reviewed.
"""

import json
import re
from collections import Counter

import pytest

from drugwatch_analytics.drug_class import (
    CLASSES,
    CLEAR,
    JUDGEMENT,
    PROPOSALS,
    UNCLASSIFIED,
    classes_for,
    ingredient_regex,
)
from drugwatch_analytics.drug_class_review import (
    accepted_vocabulary,
    coverage,
    example_for,
    findings_per_ingredient,
    load_decisions,
    save_decision,
    write_seed,
)

VOCABULARY = {ingredient: drug_class for ingredient, drug_class, _, _ in PROPOSALS}

# Words that carry no information in a reason, so they do not count as telling the reviewer
# anything they could not have guessed from the ingredient and the class alone.
STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "for",
    "in",
    "it",
    "is",
    "as",
    "also",
    "here",
    "this",
    "that",
    "its",
    "by",
    "to",
    "at",
    "on",
    "with",
    "group",
    "named",
    "spelled",
    "way",
    "same",
    "thing",
    "form",
    "only",
    "ever",
    "which",
    "not",
    "but",
    "so",
    "one",
    "two",
    "three",
    "s",
}


# --------------------------------------------------------------------------- the vocabulary itself


def test_every_proposal_has_a_reason_and_a_known_kind():
    """A proposal with no reason cannot be reviewed - it can only be rubber-stamped."""
    for ingredient, drug_class, kind, reason in PROPOSALS:
        assert kind in {CLEAR, JUDGEMENT}, ingredient
        assert len(reason) > 12, f"{ingredient}: reason too thin to review"
        assert reason.endswith("."), f"{ingredient}: reason is not a sentence"
        assert drug_class in CLASSES


def test_no_reason_merely_restates_the_class_it_proposes():
    """The real standard a reason has to meet. "Vitamin." under Vitamin / mineral supplement, or
    "Bandage." under Surgical consumable, tells a reviewer with no pharmacology nothing at all -
    they can only agree. A reason has to carry a word that neither the ingredient nor the class
    already says, or it is decoration."""
    for ingredient, drug_class, _, reason in PROPOSALS:
        said = set(re.findall(r"[a-z]+", f"{ingredient} {drug_class}".lower()))
        new_words = set(re.findall(r"[a-z]+", reason.lower())) - said - STOPWORDS
        assert new_words, f"{ingredient}: {reason!r} only restates {drug_class!r}"


def test_the_judgement_calls_say_what_the_other_reading_is():
    """A judgement call is only reviewable if the reviewer is told what they are choosing
    between. These are the ones where "n" has to be a live option."""
    judgement = [(i, r) for i, _, kind, r in PROPOSALS if kind == JUDGEMENT]
    assert len(judgement) > 20, "the hard cases should not have quietly become clear ones"
    for ingredient, reason in judgement:
        assert len(reason) > 60, f"{ingredient}: a judgement call needs its alternative stated"


def test_no_ingredient_is_proposed_twice():
    """Two classes for one ingredient would make the seed's primary key a lie."""
    repeated = [i for i, n in Counter(i for i, _, _, _ in PROPOSALS).items() if n > 1]
    assert repeated == []


def test_unclassified_is_never_a_proposed_class():
    """Unclassified is the residue, not something a person accepts for an ingredient."""
    assert UNCLASSIFIED not in CLASSES


def test_every_ingredient_is_plain_text():
    """The same string is used as a regex on both sides (Python here, Postgres in dbt), so it must
    mean the same thing to both. Anything with regex punctuation in it is rejected outright."""
    for ingredient, _, _, _ in PROPOSALS:
        assert ingredient == ingredient.lower()
        ingredient_regex(ingredient)  # raises if it is not plain text


@pytest.mark.parametrize("bad", ["Paracetamol", "a.b", "a(b", "a|b", "*x", ""])
def test_a_pattern_cannot_be_smuggled_into_the_vocabulary(bad):
    with pytest.raises(ValueError, match="not plain text"):
        ingredient_regex(bad)


# --------------------------------------------------------------------------- the match rule


def test_a_salt_name_does_not_become_an_ingredient():
    """The reason the vocabulary holds phrases and not words. 'Atorvastatin Calcium' is a statin
    formulated as a calcium salt; a word-level vocabulary calls it a mineral supplement."""
    assert classes_for("Atorvastatin Calcium Tablets IP 10mg", VOCABULARY) == ["Lipid-lowering"]
    assert classes_for("Diclofenac Sodium Tablets IP 50 mg", VOCABULARY) == [
        "Analgesic / anti-inflammatory"
    ]
    assert classes_for("Rabeprazole Sodium Injection IP", VOCABULARY) == ["Gastrointestinal"]
    assert classes_for("Thyroxine Sodium Tablets IP", VOCABULARY) == ["Hormone"]


def test_the_mineral_phrases_still_match_when_they_are_the_ingredient():
    """The other half of the same rule: these products really are supplements and fluids."""
    assert classes_for("Calcium Carbonate & Vitamin D3 Tablets", VOCABULARY) == [
        "Vitamin / mineral supplement"
    ]
    assert classes_for("Sodium Chloride Injection IP 0.9% w/v (NS)", VOCABULARY) == [
        "Fluid / electrolyte replacement"
    ]


def test_a_combination_product_carries_every_class_it_contains():
    """Why this is an array and not a column. Picking one of three needs a priority rule that
    cannot be defended, so all three are kept and the dashboard says they are counted twice."""
    found = classes_for(
        "Ambroxol Hydrochloride, Terbutaline Sulphate and Guaiphenesin Syrup", VOCABULARY
    )
    assert found == ["Respiratory / cough and cold"]
    found = classes_for("Cefixime, Azithromycin & Lactic Acid Bacillus Tablets", VOCABULARY)
    assert found == ["Antibiotic", "Probiotic"]
    found = classes_for("Aceclofenac, Paracetamol & Serratiopeptidase Tablets", VOCABULARY)
    assert found == ["Analgesic / anti-inflammatory", "Enzyme preparation"]


def test_classes_come_back_in_a_fixed_order():
    """Two products with the same classes must produce the same array, or anything grouping on it
    sees two groups where there is one."""
    both = "Amoxycillin, Potassium Clavulanate & Lactic Acid Bacillus Tablets"
    one = classes_for(both, VOCABULARY)
    two = classes_for("Lactic Acid Bacillus & Amoxycillin Tablets", VOCABULARY)
    assert one == two == ["Antibiotic", "Probiotic"]


def test_nothing_matched_is_an_empty_list_not_unclassified():
    """The caller decides what "no match" reads as; this function does not decide for it."""
    assert classes_for("Zylinta Syrup", VOCABULARY) == []


def test_a_match_must_be_a_whole_word():
    """'ringer' must not match 'Ringerol', and a substring of a longer molecule is not that
    molecule - the single most likely way a vocabulary like this goes wrong."""
    assert classes_for("Ringerol Tablets", VOCABULARY) == []
    assert ingredient_regex("ringer").search("Compound Sodium Lactate (Ringer Lactate)")
    # 'aspirin' inside a brand word is not aspirin
    assert classes_for("Aspirinox Capsules", VOCABULARY) == []


def test_matching_ignores_case_because_cdsco_prints_both():
    assert classes_for("ONDANSETRON INJECTION IP", VOCABULARY) == ["Gastrointestinal"]
    assert classes_for("ketoconazole Shampoo", VOCABULARY) == ["Antifungal"]


def test_a_misspelling_on_the_pack_is_in_the_vocabulary_on_purpose():
    """CDSCO printed 'Levocetrizine' on real findings. Matching only the correct spelling would
    silently drop them, which looks like absence of data rather than a spelling difference."""
    assert classes_for("Montelukast & Levocetrizine Hydrochloride Syrup", VOCABULARY) == [
        "Respiratory / cough and cold",
        "Antihistamine / antiallergic",
    ]


def test_things_that_are_not_medicines_are_not_given_a_therapeutic_class():
    """CDSCO tests cotton wool, syringes and hair colour to IP standards. A drug-class chart that
    hides them inside a therapeutic bucket would be stating something false."""
    assert classes_for("Absorbent Cotton Wool IP", VOCABULARY) == ["Surgical consumable or device"]
    assert classes_for("Sterile Hypodermic Syringe 5ml", VOCABULARY) == [
        "Surgical consumable or device"
    ]
    assert classes_for("VIP Hair Colour Shampoo", VOCABULARY) == ["Cosmetic or toiletry"]
    assert classes_for("Propylene Glycol IP", VOCABULARY) == ["Pharmaceutical raw material"]


# --------------------------------------------------------------------------- the review log


def test_only_accepted_entries_reach_the_vocabulary(tmp_path):
    """The whole point of the review: a proposal is not a vocabulary entry until someone says so."""
    log = tmp_path / "decisions.jsonl"
    save_decision("paracetamol", "Analgesic / anti-inflammatory", True, CLEAR, log)
    save_decision("soap", "Cosmetic or toiletry", False, JUDGEMENT, log)
    assert load_decisions(log) == {"paracetamol": True, "soap": False}
    # accepted_vocabulary reads the module-level PROPOSALS, so check it through the same filter
    decided = load_decisions(log)
    vocabulary = {i: c for i, c, _, _ in PROPOSALS if decided.get(i)}
    assert vocabulary == {"paracetamol": "Analgesic / anti-inflammatory"}


def test_a_later_answer_replaces_an_earlier_one(tmp_path):
    """Changing your mind has to be possible without editing a log by hand."""
    log = tmp_path / "decisions.jsonl"
    save_decision("menthol", "Respiratory / cough and cold", True, JUDGEMENT, log)
    save_decision("menthol", "Respiratory / cough and cold", False, JUDGEMENT, log)
    assert load_decisions(log) == {"menthol": False}


def test_every_decision_records_when_it_was_made(tmp_path):
    log = tmp_path / "decisions.jsonl"
    save_decision("aspirin", "Blood and clotting", True, JUDGEMENT, log)
    row = json.loads(log.read_text().splitlines()[0])
    assert row["kind"] == JUDGEMENT
    assert row["decided_at"].endswith("+00:00")


def test_an_undecided_proposal_is_not_in_the_vocabulary(tmp_path):
    assert accepted_vocabulary(tmp_path / "nothing.jsonl") == {}


# --------------------------------------------------------------------------- the seed


def test_the_seed_is_sorted_and_carries_no_counts(tmp_path):
    """Sorted so re-writing it is a clean diff; no counts because the seed is a claim about
    pharmacology, and a measurement mixed in would look like the archive had said it."""
    seed = tmp_path / "drug_class_vocabulary.csv"
    rows = {"zinc sulphate": "Vitamin / mineral supplement", "aspirin": "Blood"}
    written = write_seed(rows, seed)
    assert written == 2
    assert seed.read_text() == (
        "ingredient,drug_class\naspirin,Blood\nzinc sulphate,Vitamin / mineral supplement\n"
    )


def test_writing_the_seed_twice_produces_the_same_file(tmp_path):
    seed = tmp_path / "drug_class_vocabulary.csv"
    write_seed(VOCABULARY, seed)
    first = seed.read_text()
    write_seed(VOCABULARY, seed)
    assert seed.read_text() == first


# ----------------------------------------------------------------------- the review's arithmetic


NAMES = [
    ("Paracetamol Tablets IP 500 mg", 25),
    ("Cefixime, Azithromycin & Lactic Acid Bacillus Tablets", 4),
    ("Zylinta Syrup", 3),
]


def test_findings_per_ingredient_counts_findings_not_product_names():
    """A product name with 25 findings is 25 findings. Counting names instead would make the
    commonest medicine in the archive look as rare as a one-off."""
    counts = findings_per_ingredient(NAMES)
    assert counts["paracetamol"] == 25
    assert counts["cefixime"] == 4
    assert counts["telmisartan"] == 0


def test_the_example_shown_is_the_biggest_one():
    """A reviewer should see the product the decision most affects, not an arbitrary row."""
    assert example_for("paracetamol", NAMES) == "Paracetamol Tablets IP 500 mg"
    assert example_for("telmisartan", NAMES) == "(nothing in the archive)"


def test_coverage_reports_the_unclassified_remainder_and_the_double_counting():
    """Both numbers are the ones a reader needs to not be misled, so neither may be dropped."""
    report = coverage(VOCABULARY, NAMES)
    assert "29 of 32 findings (90.6%); 3 stay Unclassified" in report
    assert "4 finding(s) carry more than one class" in report


def test_coverage_stays_silent_about_double_counting_when_there_is_none():
    """A report saying "0 findings carry more than one class, so the classes add up to more than
    the total" contradicts itself, and a reader who notices stops trusting the rest of it."""
    report = coverage({"paracetamol": "Analgesic / anti-inflammatory"}, NAMES)
    assert "more than one class" not in report
    assert "25 of 32 findings" in report
