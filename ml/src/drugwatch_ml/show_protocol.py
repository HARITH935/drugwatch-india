"""Print the split protocol against the real feature table, with what each fold actually holds.

Step 1's output. The numbers matter as much as the dates: a fold with 300 positives supports a very
different claim from one with 3,000, and the embargo's cost should be a number somebody looked at
rather than a design detail.

Run from ml/, with Postgres up and gold loaded:
    uv run --env-file ../.env python -m drugwatch_ml.show_protocol
"""

from drugwatch_ml import features, splits


def row(label: str, frame, total: int) -> str:
    if len(frame) == 0:
        return f"  {label:28s} {'0':>7}"
    positives = int(frame[features.LABEL_COLUMN].sum())
    return (
        f"  {label:28s} {len(frame):>7,} rows "
        f"{frame['manufacturer_id'].nunique():>6,} companies "
        f"{positives:>6,} positive ({positives / len(frame):5.1%}) "
        f"{len(frame) / total:5.1%} of all"
    )


def main() -> int:
    frame = features.load_features()
    features.check_columns(frame)
    newest = str(frame["as_of_month"].max())
    total = len(frame)
    print(f"{total:,} labelled rows, cutoffs {frame['as_of_month'].min()}..{newest}\n")

    tuning, test = splits.protocol(newest)

    print("TUNING - chooses hyperparameters, thresholds, which model to prefer")
    for fold in tuning:
        print(f"\n{fold.describe()}")
        training, evaluation = splits.split(frame, fold)
        print(row("train", training, total))
        print(row("validate", evaluation, total))

    print("\nTEST - evaluated once, never tuned against")
    print(f"\n{test.describe()}")
    final_training, test_rows = splits.split(frame, test)
    print(row("train (final fit)", final_training, total))
    print(row("test", test_rows, total))

    embargoed = frame[frame["as_of_month"].isin(test.embargoed)]
    print(
        f"\nthe test embargo discards {len(embargoed):,} rows"
        f" ({len(embargoed) / total:.1%}) across {len(test.embargoed)} cutoffs"
        f" - the price of the test set not being told its own answers"
    )

    # The protocol's one invariant, checked on the real rows rather than only in the unit tests.
    overlap = set(final_training["as_of_month"]) & set(test_rows["as_of_month"])
    print(f"cutoffs in both the final training set and the test set: {len(overlap)}")

    # Who the test set is actually about. Nearly half its companies have no row in training at
    # all, because a company gets cutoff rows only from its first finding onwards - so the test
    # measures two different regimes and step 5 has to report them apart. A single headline number
    # would average over "a company the model has watched for years" and "a company it is seeing
    # for the first time", which are not the same prediction.
    known = set(final_training["manufacturer_id"])
    is_known = test_rows["manufacturer_id"].isin(known)
    print("\nwho the test set is about:")
    print(row("seen during training", test_rows[is_known], total))
    print(row("new since training", test_rows[~is_known], total))
    new_companies = test_rows[~is_known]["manufacturer_id"].nunique()
    all_companies = test_rows["manufacturer_id"].nunique()
    print(
        f"  {new_companies:,} of {all_companies:,} test companies"
        f" ({new_companies / all_companies:.0%}) are new. They still have features - their own"
        " history up to the cutoff - but the model never trained on them, which is the honest"
        ' reason this score cannot answer "is this company risky?".'
    )
    return 0 if not overlap else 1


if __name__ == "__main__":
    raise SystemExit(main())
