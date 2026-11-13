"""Phase 3 step 5, piece 3: decide the borderline manufacturer pairs by hand.

Piece 2 merges pairs scoring 98+ on its own and leaves the 260 pairs scoring 95-98 alone, because
reading real examples showed that band mixes true matches with pairs like "RPL (INDIA)
Pharmaceuticals Private Limited" / "ZRS Pharmaceuticals India Private Limited" (95.1, two
different companies). CLAUDE.md Section 5: a missed merge is better than a wrong merge, so a
person decides those, and this module is how.

Sorting the 260 by what actually differs (checked against all of them, 2026-11-13):

  SPACING (13 pairs)  Only spaces or punctuation move: "Pharma Roots" / "Pharmaroots". No letter
                      changes, so these are safe to accept as a batch.
  COMMON_TYPO (87)    Every differing word is a misspelling of a word that appears across many
                      DIFFERENT companies: "Pharmaceuticlas" -> "Pharmaceuticals", "&" -> "and",
                      "Hidustan Antibitics" -> "Hindustan Antibiotics". One spelling is a real
                      word and the other plainly is not, so these are safe as a batch too.
  JUDGEMENT (160)     The difference touches the DISTINCTIVE part of the name, where a typo and a
                      second real company look identical: "Agron" / "Argon", "Sai" / "Sia",
                      "Dexbio" / "Dexibo", "Shell Eastern Chemicals" / "... (S)". Asked one at a
                      time; nothing here is ever decided automatically.

Why a word counts as "common" only when it is 3+ letters long: "(S)" reduces to the token "s",
which appears all over the archive, so a length-blind rule called "Shell Eastern Chemicals" and
"Shell Eastern Chemicals (S)" a typo of each other. The "(S)" is far more likely a separate legal
entity, so short tokens always go to JUDGEMENT.

The JUDGEMENT pairs are asked most-obviously-a-typo first (typo_likelihood): a one-letter slip in
a long word ("Daffohills"/"Daffohils", 0.95) is nearly always a typo, while a pair whose only
difference is a whole extra token ("Nestor Pharmaceuticals Limited" / "... Limited II", 0.00) may
well be two plants of one company, or two companies - the hardest calls come last, when it is
clear they need thought, rather than buried in the middle.

Deliberately NOT grouped: connecting the pairs into clusters and asking once per cluster would be
fewer questions, but it chains different companies together - "Apple Formulations" / "Apex
Formulations" / "APT Formulations" land in one group, as do "Spen" and "Super Formulations". One
yes would merge all three. So every JUDGEMENT pair is its own question.

Decisions append to ../data/manufacturer-review/decisions.jsonl (git-ignored, like the eval-set
labels: it holds real CDSCO names) as each one is made, so the review can stop and resume.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.manufacturer_review --batches  # the 100
    uv run --env-file ../.env python -m drugwatch_spark.manufacturer_review            # the 160
"""

import json
import re
import sys
import termios
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rapidfuzz import fuzz, utils
from rapidfuzz.distance import Levenshtein

DECISIONS = Path(__file__).resolve().parents[3] / "data" / "manufacturer-review" / "decisions.jsonl"
MIN_NAMES_FOR_COMMON = 15  # a word in this many different companies' names is a common word
MIN_COMMON_LENGTH = 3  # "(S)" -> "s": too short to ever call a typo
SPACING, COMMON_TYPO, JUDGEMENT = "spacing", "common-word typo", "judgement"
# Reading one pair properly takes longer than this; faster means keys were held down.
MIN_SECONDS = 2.0


def _normalise(text: str) -> str:
    return utils.default_process(text)


def squashed(text: str) -> str:
    """Only the letters and digits: what is left when spacing and punctuation stop counting."""
    return re.sub(r"[^a-z0-9]", "", _normalise(text))


def words_in(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalise(text))


def common_words(names: list[str]) -> set[str]:
    """Words shared across many DIFFERENT companies - the generic part of a pharma name."""
    seen = Counter()
    for name in names:
        for word in set(words_in(name)):
            seen[word] += 1
    return {
        word
        for word, how_many in seen.items()
        if how_many >= MIN_NAMES_FOR_COMMON and len(word) >= MIN_COMMON_LENGTH
    }


def differing_words(left: str, right: str) -> tuple[list[str], list[str]]:
    """The words each side has that the other doesn't."""
    in_left, in_right = Counter(words_in(left)), Counter(words_in(right))
    return list((in_left - in_right).elements()), list((in_right - in_left).elements())


def _is_misspelling_of_a_common_word(word: str, common: set[str]) -> bool:
    if word in common:
        return True
    return any(
        Levenshtein.distance(word, known) <= 2
        and abs(len(word) - len(known)) <= 2
        and fuzz.ratio(word, known) >= 85
        for known in common
    )


def classify(left: str, right: str, common: set[str]) -> str:
    """SPACING, COMMON_TYPO or JUDGEMENT - see this module's docstring for what each means."""
    if squashed(left) == squashed(right):
        return SPACING
    only_left, only_right = differing_words(left, right)
    if all(_is_misspelling_of_a_common_word(w, common) for w in only_left + only_right):
        return COMMON_TYPO
    return JUDGEMENT


def typo_likelihood(left: str, right: str) -> float:
    """0-1: how much the difference looks like a slip of the finger rather than another name.
    0 when one side simply has a word the other hasn't (an extra "II" or "(S)" is not a typo)."""
    only_left, only_right = differing_words(left, right)
    if not only_left or not only_right:
        return 0.0
    worst = 1.0
    for word in only_left:
        closest = max((fuzz.ratio(word, other) / 100 for other in only_right), default=0.0)
        worst = min(worst, closest)
    return worst


def sort_for_review(pairs: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    """Most-obviously-a-typo first, so the genuinely hard calls come last, not buried."""
    return sorted(pairs, key=lambda p: (-typo_likelihood(p[0], p[1]), p[0], p[1]))


def split_by_kind(
    pairs: list[tuple[str, str, float]], common: set[str]
) -> dict[str, list[tuple[str, str, float]]]:
    groups: dict[str, list[tuple[str, str, float]]] = {SPACING: [], COMMON_TYPO: [], JUDGEMENT: []}
    for left, right, score in pairs:
        groups[classify(left, right, common)].append((left, right, score))
    groups[JUDGEMENT] = sort_for_review(groups[JUDGEMENT])
    return groups


def load_decisions(path: Path = DECISIONS) -> dict[tuple[str, str], bool]:
    """Every decision made so far; a later answer for a pair replaces an earlier one."""
    if not path.exists():
        return {}
    decided = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            decided[(row["left"], row["right"])] = row["same"]
    return decided


def save_decision(left: str, right: str, same: bool, kind: str, path: Path = DECISIONS) -> None:
    """Append one decision straight away, so stopping never loses the ones already made."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "left": left,
        "right": right,
        "same": same,
        "kind": kind,
        "decided_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with path.open("a") as out:
        out.write(json.dumps(row) + "\n")


def merges_from_decisions(path: Path = DECISIONS) -> list[tuple[str, str]]:
    """The pairs a person said are the same company."""
    return [pair for pair, same in load_decisions(path).items() if same]


def ask_now(prompt: str) -> str:
    """Throw away anything typed before the question appeared, then ask (same guard as the
    eval-set labeller: a held-down key must never answer the next question).

    Ctrl-D (or input running out) reads as "q": stopping that way is normal, and every decision
    so far is already saved, so it should end the review quietly rather than print a traceback.
    """
    if sys.stdin.isatty():
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    try:
        return input(prompt)
    except EOFError:
        return "q"


def ask_about(
    left: str,
    right: str,
    score: float,
    ask: Callable[[str], str] = ask_now,
    clock: Callable[[], float] = time.monotonic,
) -> bool | None:
    """Ask whether two names are the same company. True/False, or None to stop.
    Asks again if the answer came back faster than a person can read two names."""
    while True:
        started = clock()
        print(f"\n  A: {left}")
        print(f"  B: {right}")
        answer = ask(f"  same company? [y/n/q]  (similarity {score:.1f})  ").strip().lower()
        if answer in {"q", "/q"}:
            return None
        if answer not in {"y", "n"}:
            print("  please answer y (same), n (different) or q (stop)")
            continue
        if clock() - started < MIN_SECONDS:
            print("  that was too quick to have read both names - asking again")
            continue
        return answer == "y"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batches",
        action="store_true",
        help="show the spacing-only and common-word-typo pairs and accept them as two batches",
    )
    args = parser.parse_args()

    from pyspark.sql import functions as F

    from drugwatch_spark.manufacturer_cluster import review_candidates
    from drugwatch_spark.manufacturer_name import add_clean_manufacturer_name
    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("manufacturer-review")
    try:
        names = None
        for path in (PDF, PORTAL):
            cleaned = add_clean_manufacturer_name(read_bronze(spark, path), F.col("manufacturer"))
            column = cleaned.select("manufacturer_name")
            names = column if names is None else names.union(column)
        counts = {
            row["manufacturer_name"]: row["count"]
            for row in names.where(F.col("manufacturer_name").isNotNull())
            .groupBy("manufacturer_name")
            .count()
            .collect()
        }
    finally:
        spark.stop()

    pairs = review_candidates(counts)
    groups = split_by_kind(pairs, common_words(list(counts)))
    already = load_decisions()
    print(
        f"{len(pairs)} borderline pairs: " + ", ".join(f"{len(v)} {k}" for k, v in groups.items())
    )

    if args.batches:
        for kind in (SPACING, COMMON_TYPO):
            todo = [p for p in groups[kind] if (p[0], p[1]) not in already]
            if not todo:
                print(f"\n{kind}: all {len(groups[kind])} already decided")
                continue
            print(f"\n=== {kind}: {len(todo)} pairs ===")
            for left, right, _ in todo:
                print(f"  {left}\n  {right}\n")
            answer = ask_now(f"accept all {len(todo)} as the same company? [y/N] ").strip().lower()
            if answer == "y":
                for left, right, _ in todo:
                    save_decision(left, right, True, kind)
                print(f"  saved {len(todo)} merges")
            else:
                print("  left undecided")
        return

    todo = [p for p in groups[JUDGEMENT] if (p[0], p[1]) not in already]
    print(f"\n{len(todo)} of {len(groups[JUDGEMENT])} judgement pairs left, easiest first.")
    print("Answer y (same company), n (different), or q to stop - each one is saved as you go.")
    for number, (left, right, score) in enumerate(todo, start=1):
        print(f"\n[{number}/{len(todo)}]", end="")
        same = ask_about(left, right, score)
        if same is None:
            print(f"\nstopped; {number - 1} decided this session, all saved")
            return
        save_decision(left, right, same, JUDGEMENT)
    print(f"\nall done: {len(todo)} decided this session")


if __name__ == "__main__":
    main()
