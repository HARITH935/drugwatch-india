"""manufacturer_review.py: the three kinds of difference, the ordering, and the safety nets."""

import json

import pytest

from drugwatch_spark.manufacturer_review import (
    COMMON_TYPO,
    JUDGEMENT,
    SPACING,
    ask_about,
    ask_now,
    classify,
    common_words,
    load_decisions,
    merges_from_decisions,
    save_decision,
    sort_for_review,
    split_by_kind,
    typo_likelihood,
)

# The words the real archive makes common, listed outright: deriving them from a handful of made
# up names would need 15 copies of each word and still not match what the real data produces.
COMMON = {
    "pharmaceuticals", "pharmaceutical", "private", "limited", "chemicals", "healthcare",
    "laboratories", "antibiotics", "hindustan", "bengal", "remedies", "pharma", "formulations",
    "and", "plot", "unit", "lab", "health", "care", "medicare", "devices", "biotech",
}  # fmt: skip


def test_common_words_are_the_shared_ones_not_the_distinctive_ones():
    # 20 companies share "pharmaceuticals"; each keeps its own distinctive first word.
    archive = [f"Maker{i} Pharmaceuticals Private Limited" for i in range(20)]

    common = common_words(archive)

    assert "pharmaceuticals" in common
    assert "limited" in common
    assert "maker3" not in common  # a company's own name is never a common word


def test_a_short_token_is_never_treated_as_a_common_word():
    # "(S)" reduces to the token "s", which really is all over the archive. Counting it as a
    # common word made "Shell Eastern Chemicals" and "Shell Eastern Chemicals (S)" look like
    # typos of each other, when "(S)" is far more likely a separate legal entity.
    archive = [f"Maker{i} (S) Pharmaceuticals Limited" for i in range(20)]

    common = common_words(archive)

    assert "s" not in common  # frequent, but too short to ever be a typo of anything
    assert "pharmaceuticals" in common  # long and frequent: genuinely common
    assert classify("Shell Eastern Chemicals", "Shell Eastern Chemicals (S)", common) == JUDGEMENT


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Pharma Roots Healthcare", "Pharmaroots Healthcare"),  # a space moves
        ("Life Vision Healthcare", "Lifevision Healthcare"),
        ("Healer's Lab Unit II Plot NO. 33", "Healers Lab Unit II Plot No. 33"),  # punctuation
    ],
)
def test_spacing_only_differences(left, right):
    assert classify(left, right, COMMON) == SPACING


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Real pairs: one spelling is a real word, the other plainly is not.
        (
            "Bengal Chemicals & Pharmaceuticlas Limited",
            "Bengal Chemicals & Pharmaceuticals Limited",
        ),
        ("Hidustan Antibitics Limited", "Hindustan Antibiotics Limited"),
    ],
)
def test_a_misspelled_common_word(left, right):
    assert classify(left, right, COMMON) == COMMON_TYPO


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Real pairs where a typo and a second real company look identical.
        ("Agron Remedies Private Limited", "Argon Remedies Private Limited"),
        ("Sai Pharma Private Limited", "Sia Pharma Private Limited"),
        ("Dexbio Pharma Private Limited", "Dexibo Pharma Private Limited"),
    ],
)
def test_the_distinctive_part_differing_always_needs_a_person(left, right):
    assert classify(left, right, COMMON) == JUDGEMENT


def test_an_obvious_typo_is_asked_before_a_genuinely_hard_pair():
    # A one-letter slip in a long word vs. a whole extra token (a possible second plant).
    obvious = typo_likelihood("Daffohills Laboratories", "Daffohils Laboratoies")
    hard = typo_likelihood("Nestor Pharmaceuticals Limited", "Nestor Pharmaceuticals Limited II")

    assert obvious > hard
    assert hard == 0.0  # an extra word is never a slip of the finger


def test_sort_for_review_puts_the_hard_calls_last():
    pairs = [
        ("Nestor Pharmaceuticals Limited", "Nestor Pharmaceuticals Limited II", 97.0),
        ("Daffohills Laboratories", "Daffohils Laboratoies", 96.0),
    ]

    assert sort_for_review(pairs)[0][0] == "Daffohills Laboratories"


def test_split_by_kind_counts_each_pair_once():
    pairs = [
        ("Pharma Roots Healthcare", "Pharmaroots Healthcare", 97.0),
        ("Hidustan Antibitics Limited", "Hindustan Antibiotics Limited", 96.0),
        ("Agron Remedies Private Limited", "Argon Remedies Private Limited", 97.0),
    ]

    groups = split_by_kind(pairs, COMMON)

    assert [len(groups[k]) for k in (SPACING, COMMON_TYPO, JUDGEMENT)] == [1, 1, 1]


def test_split_by_kind_hands_back_the_judgement_pairs_in_asking_order():
    pairs = [
        # The hard one first on input: an extra token may be a second plant, not a typo.
        ("Nestor Pharmaceuticals Limited", "Nestor Pharmaceuticals Limited II", 97.0),
        ("Daffohills Laboratories", "Daffohils Laboratoies", 96.0),  # a plain one-letter slip
    ]

    judgement = split_by_kind(pairs, COMMON)[JUDGEMENT]

    assert [left for left, _, _ in judgement] == [
        "Daffohills Laboratories",  # asked first, while the easy ones are quick
        "Nestor Pharmaceuticals Limited",  # the call needing thought comes last
    ]


def test_decisions_are_saved_and_read_back(tmp_path):
    path = tmp_path / "decisions.jsonl"

    save_decision("Agron Remedies", "Argon Remedies", False, JUDGEMENT, path)
    save_decision("Zest Pharma", "Zest Pharama", True, COMMON_TYPO, path)

    assert load_decisions(path) == {
        ("Agron Remedies", "Argon Remedies"): False,
        ("Zest Pharma", "Zest Pharama"): True,
    }
    assert merges_from_decisions(path) == [("Zest Pharma", "Zest Pharama")]


def test_a_later_answer_replaces_an_earlier_one(tmp_path):
    path = tmp_path / "decisions.jsonl"

    save_decision("A Pharma", "B Pharma", True, JUDGEMENT, path)
    save_decision("A Pharma", "B Pharma", False, JUDGEMENT, path)  # changed their mind

    assert load_decisions(path) == {("A Pharma", "B Pharma"): False}
    assert merges_from_decisions(path) == []


def test_every_decision_records_what_it_was_and_when(tmp_path):
    path = tmp_path / "decisions.jsonl"

    save_decision("A Pharma", "B Pharma", True, JUDGEMENT, path)

    row = json.loads(path.read_text().splitlines()[0])
    assert row["kind"] == JUDGEMENT
    assert row["same"] is True
    assert row["decided_at"]  # provenance: when this call was made


def test_an_answer_too_fast_to_have_been_read_is_asked_again():
    answers = iter(["y", "y"])
    times = iter([0.0, 0.1, 10.0, 20.0])  # first answer 0.1s later, second properly spaced

    same = ask_about("A Pharma", "B Pharma", 97.0, ask=lambda _: next(answers),
                     clock=lambda: next(times))  # fmt: skip

    assert same is True
    assert next(answers, "used up") == "used up"  # it really did ask twice


def test_an_unknown_key_is_not_taken_as_an_answer():
    answers = iter(["x", "n"])
    times = iter([0.0, 10.0, 20.0, 30.0])

    same = ask_about("A Pharma", "B Pharma", 97.0, ask=lambda _: next(answers),
                     clock=lambda: next(times))  # fmt: skip

    assert same is False
    # It must have asked again rather than reading "x" as "not y": both answers were used.
    assert next(answers, "used up") == "used up"


def test_q_stops_the_review():
    assert ask_about("A", "B", 97.0, ask=lambda _: "q", clock=lambda: 0.0) is None


def test_ctrl_d_stops_the_review_instead_of_crashing(monkeypatch):
    # Ctrl-D, or piped input running out, used to raise EOFError and print a traceback over a
    # review whose decisions were all already saved.
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))

    assert ask_now("ignored") == "q"
    assert ask_about("A", "B", 97.0, clock=lambda: 0.0) is None
