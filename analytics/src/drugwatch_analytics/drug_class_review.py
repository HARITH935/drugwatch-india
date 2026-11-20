"""Review the proposed drug-class vocabulary, one batch at a time, and write the dbt seed.

Phase 6 step 3c, decision B (ADR 0014). The proposals and the match rule are in `drug_class.py`;
this is the part where a person decides which of them are true. Same shape as Phase 3's
`manufacturer_review`, for the same reason: a mapping that nobody checked is a guess with a
schema.

What is asked, and how:

  CLEAR (188 entries, offered as one batch per class)
      The class is the ingredient's textbook use and there was nothing to choose: paracetamol is a
      painkiller, cefixime is an antibiotic. The whole batch is printed - every ingredient, its
      reason, how many findings it matches and a real product name - and accepted or rejected as
      one. Reading 23 antibiotics is quicker than answering 23 questions, and the decision is the
      same decision.

  JUDGEMENT (28 entries, asked one at a time)
      Somewhere a choice was made. Aspirin is a painkiller at full dose and a clot preventer at
      the low dose used here. Menthol is a decongestant in a cough syrup and a skin coolant in a
      pain gel. Cotton wool is not a drug at all. Each one prints the reason the proposal might be
      wrong before asking, and `n` is a perfectly good answer - a rejected entry simply leaves
      those products Unclassified, which is the honest outcome when nobody can say.

Decisions append to ../data/drug-class-review/decisions.jsonl as they are made, so the review can
stop and resume. That file is git-ignored like the other review logs; the *accepted* vocabulary is
written to dbt/seeds/drug_class_vocabulary.csv by --seed and is committed, because an ingredient's
pharmacological class is published knowledge rather than anything taken from a CDSCO row.

Run (from analytics/, Postgres up with gold loaded):
    uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review --batches  # the 188
    uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review            # the 28
    uv run --env-file ../.env python -m drugwatch_analytics.drug_class_review --seed     # write it
"""

import argparse
import csv
import json
import sys
import termios
import textwrap
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from drugwatch_analytics.drug_class import (
    CLASSES,
    CLEAR,
    JUDGEMENT,
    PROPOSALS,
    classes_for,
    ingredient_regex,
)

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "data" / "drug-class-review" / "decisions.jsonl"
SEED = REPO / "dbt" / "seeds" / "drug_class_vocabulary.csv"
MIN_SECONDS = 2.0  # reading a reason takes longer than this; faster means a key was held down


def load_decisions(path: Path = DECISIONS) -> dict[str, bool]:
    """Every decision so far, ingredient -> accepted. A later answer replaces an earlier one."""
    if not path.exists():
        return {}
    decided: dict[str, bool] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            decided[row["ingredient"]] = row["accepted"]
    return decided


def save_decision(
    ingredient: str, drug_class: str, accepted: bool, kind: str, path: Path = DECISIONS
) -> None:
    """Append one decision immediately, so stopping never loses what was already decided."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write(
            json.dumps(
                {
                    "ingredient": ingredient,
                    "drug_class": drug_class,
                    "accepted": accepted,
                    "kind": kind,
                    "decided_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            + "\n"
        )


def accepted_vocabulary(path: Path = DECISIONS) -> dict[str, str]:
    """ingredient -> class, for the entries a person accepted. Nothing else is a vocabulary."""
    decided = load_decisions(path)
    return {
        ingredient: drug_class
        for ingredient, drug_class, _, _ in PROPOSALS
        if decided.get(ingredient)
    }


def write_seed(vocabulary: Mapping[str, str], path: Path = SEED) -> int:
    """Write the accepted vocabulary as a dbt seed, sorted so a re-run is a clean diff.

    No count from the archive goes in here: the seed is a claim about pharmacology, and mixing a
    measurement into it would make it look like the archive said something it did not.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["ingredient", "drug_class"])
        for ingredient in sorted(vocabulary):
            writer.writerow([ingredient, vocabulary[ingredient]])
    return len(vocabulary)


def findings_per_ingredient(names: Sequence[tuple[str, int]]) -> Counter[str]:
    """How many findings each proposed ingredient would match, for the review to show.

    Counted here rather than in SQL because the review has to run before any seed exists, so there
    is no table to query. A test checks this agrees with the dbt model once the seed is written.
    """
    counts: Counter[str] = Counter()
    for ingredient, _, _, _ in PROPOSALS:
        pattern = ingredient_regex(ingredient)
        counts[ingredient] = sum(n for name, n in names if pattern.search(name))
    return counts


def example_for(ingredient: str, names: Sequence[tuple[str, int]]) -> str:
    """The product name with the most findings that this ingredient matches."""
    pattern = ingredient_regex(ingredient)
    hits = sorted(((n, name) for name, n in names if pattern.search(name)), reverse=True)
    return " ".join(hits[0][1].split()) if hits else "(nothing in the archive)"


def coverage(vocabulary: Mapping[str, str], names: Sequence[tuple[str, int]]) -> str:
    """What this vocabulary would do to the archive: matched, unclassified, and per class."""
    total = sum(n for _, n in names)
    per_class: Counter[str] = Counter()
    multi = matched = 0
    for name, n in names:
        found = classes_for(name, dict(vocabulary))
        if found:
            matched += n
        if len(found) > 1:
            multi += n
        for drug_class in found:
            per_class[drug_class] += n
    lines = [
        f"{len(vocabulary)} accepted ingredient(s) classify {matched} of {total} findings"
        f" ({matched / total:.1%}); {total - matched} stay Unclassified."
    ]
    # Only said when it is true: "0 findings carry more than one class, so the classes add up to
    # more than the total" is a sentence that contradicts itself, and a reader who spots that
    # stops trusting the rest of the report.
    if multi:
        lines.append(
            f"{multi} finding(s) carry more than one class, so the classes add up to more than"
            " the total - a combination product counts under each of its classes."
        )
    lines += [f"  {n:5d} {n / total:5.1%}  {c}" for c, n in per_class.most_common()]
    return "\n".join(lines)


def ask_now(prompt: str) -> str:
    """Throw away anything typed before the question appeared, then ask (the same guard as the
    eval-set labeller and the manufacturer review: a held-down key must never answer the next
    question). Ctrl-D reads as "q", because stopping that way is normal."""
    if sys.stdin.isatty():
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    try:
        return input(prompt)
    except EOFError:
        return "q"


def ask_about(
    ingredient: str,
    drug_class: str,
    reason: str,
    findings: int,
    example: str,
    ask: Callable[[str], str] = ask_now,
    clock: Callable[[], float] = time.monotonic,
) -> bool | None:
    """Ask about one judgement call. True/False, or None to stop.

    Asks again if the answer came back faster than the reason can be read - the reason is the
    whole point of these being asked one at a time.
    """
    while True:
        started = clock()
        print(f"\n  {ingredient}  ->  {drug_class}")
        print(f"  {findings} finding(s), e.g. {example}")
        # Wrapped, not printed as one long line: an unwrapped paragraph in a terminal is a
        # paragraph that gets skimmed, and the reason is the only thing making this reviewable.
        for line in textwrap.wrap(f"why this might be wrong: {reason}", width=92):
            print(f"  {line}")
        answer = ask("  accept this class? [y/n/q]  ").strip().lower()
        if answer in {"q", "/q"}:
            return None
        if answer not in {"y", "n"}:
            print("  please answer y (accept), n (leave those products Unclassified) or q (stop)")
            continue
        if clock() - started < MIN_SECONDS:
            print("  that was too quick to have read the reason - asking again")
            continue
        return answer == "y"


def _product_names() -> list[tuple[str, int]]:
    from drugwatch_analytics.gold import query

    rows = query(
        """
        select d.product_name, count(*) as findings
        from gold.fact_nsq_sample f
        join gold.dim_drug d using (drug_id)
        group by 1
        """
    )
    return [(name, int(n)) for name, n in zip(rows["product_name"], rows["findings"], strict=True)]


def _run_batches(names: list[tuple[str, int]], already: dict[str, bool]) -> None:
    counts = findings_per_ingredient(names)
    by_class: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ingredient, drug_class, kind, reason in PROPOSALS:
        if kind == CLEAR and ingredient not in already:
            by_class[drug_class].append((ingredient, reason))

    if not by_class:
        print("every clear proposal is already decided; now run without --batches")
        return
    print(f"\n{len(by_class)} class(es) left to review as batches. 'q' stops; each batch is saved.")
    for drug_class in CLASSES:
        batch = by_class.get(drug_class)
        if not batch:
            continue
        print(f"\n=== {drug_class} - {len(batch)} ingredient(s) ===")
        for ingredient, reason in sorted(batch, key=lambda row: -counts[row[0]]):
            print(f"  {ingredient:24s} {counts[ingredient]:5d} findings  {reason}")
            print(f"  {'':24s}       e.g. {example_for(ingredient, names)}")
        answer = ask_now(f"  accept all {len(batch)} as {drug_class}? [y/n/q] ").strip().lower()
        if answer in {"q", "/q"}:
            print("stopped; every batch answered so far is saved")
            return
        accepted = answer == "y"
        for ingredient, _ in batch:
            save_decision(ingredient, drug_class, accepted, CLEAR)
        print(f"  {'accepted' if accepted else 'rejected'} {len(batch)}")
    print("\nall clear batches decided. Next: run without --batches for the judgement calls.")


def _run_judgement(names: list[tuple[str, int]], already: dict[str, bool]) -> None:
    counts = findings_per_ingredient(names)
    todo = [
        (ingredient, drug_class, reason)
        for ingredient, drug_class, kind, reason in PROPOSALS
        if kind == JUDGEMENT and ingredient not in already
    ]
    if not todo:
        print("every judgement call is already decided; now run --seed")
        return
    print(f"\n{len(todo)} judgement call(s) left. Each one prints why the proposal might be wrong.")
    print("'n' is a real answer: it leaves those products Unclassified instead of mislabelled.")
    for number, (ingredient, drug_class, reason) in enumerate(todo, start=1):
        print(f"\n[{number}/{len(todo)}]", end="")
        accepted = ask_about(
            ingredient, drug_class, reason, counts[ingredient], example_for(ingredient, names)
        )
        if accepted is None:
            print(f"\nstopped; {number - 1} decided this session, all saved")
            return
        save_decision(ingredient, drug_class, accepted, JUDGEMENT)
    print(f"\nall {len(todo)} decided. Next: run --seed to write the dbt seed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--batches", action="store_true", help="review the clear proposals, one batch per class"
    )
    group.add_argument(
        "--seed", action="store_true", help="write dbt/seeds/drug_class_vocabulary.csv"
    )
    group.add_argument(
        "--coverage", action="store_true", help="what the accepted vocabulary covers, and what not"
    )
    args = parser.parse_args()

    already = load_decisions()
    kinds = Counter(kind for _, _, kind, _ in PROPOSALS)
    print(
        f"{len(PROPOSALS)} proposals across {len(CLASSES)} classes:"
        f" {kinds[CLEAR]} clear, {kinds[JUDGEMENT]} judgement."
        f" {len(already)} already decided ({sum(already.values())} accepted)."
    )

    if args.seed:
        vocabulary = accepted_vocabulary()
        if not vocabulary:
            print("nothing accepted yet - run --batches first")
            raise SystemExit(1)
        written = write_seed(vocabulary)
        print(f"wrote {written} row(s) to {SEED.relative_to(REPO)}")
        print(coverage(vocabulary, _product_names()))
        print("\nNext: cd ../dbt && uv run --env-file ../.env dbt build")
        return

    names = _product_names()
    if args.coverage:
        vocabulary = accepted_vocabulary()
        print(coverage(vocabulary, names) if vocabulary else "nothing accepted yet")
        return
    if args.batches:
        _run_batches(names, already)
    else:
        _run_judgement(names, already)


if __name__ == "__main__":
    main()
