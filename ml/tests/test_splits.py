"""The split protocol, and the leak it exists to prevent.

The tests that matter here are the ones that would pass if the embargo were removed. A split on
the cutoff date alone looks clean and is not, so these assert on **label windows**, not dates.
"""

import pandas as pd
import pytest

from drugwatch_ml.splits import (
    LABEL_HORIZON_MONTHS,
    Fold,
    final_training_end,
    label_window,
    months_between,
    protocol,
    rolling_folds,
    shift_month,
    split,
)

# ------------------------------------------------------------------ month arithmetic


@pytest.mark.parametrize(
    ("month", "by", "expected"),
    [
        ("2025-01", 1, "2025-02"),
        ("2025-12", 1, "2026-01"),
        ("2025-01", -1, "2024-12"),
        ("2026-03", -6, "2025-09"),
        ("2025-06", 0, "2025-06"),
        ("2025-01", -12, "2024-01"),
    ],
)
def test_shifting_months_crosses_years_correctly(month, by, expected):
    """Whole months, not 30-day arithmetic: adding 30 days to a cutoff lands in the wrong month
    twice a year, and every window in this protocol is counted in months."""
    assert shift_month(month, by) == expected


def test_shifting_is_reversible():
    for by in range(-24, 25):
        assert shift_month(shift_month("2025-07", by), -by) == "2025-07"


def test_months_between_is_signed():
    assert months_between("2025-01", "2025-07") == 6
    assert months_between("2025-07", "2025-01") == -6
    assert months_between("2025-01", "2025-01") == 0


def test_a_label_window_is_the_months_after_the_cutoff_not_the_cutoff():
    """The whole reason an embargo is needed. A row's label is a fact about the future, so it
    cannot be placed on the timeline at its own cutoff."""
    assert label_window("2025-03") == ("2025-04", "2025-09")
    assert "2025-03" not in label_window("2025-03")


# ------------------------------------------------------------------ the embargo


def test_a_fold_with_no_embargo_is_refused():
    """This is the bug. Training to 2025-03 and testing from 2025-04 shares five of the six
    months the test is scored on - and a date-based split shows nothing wrong."""
    with pytest.raises(ValueError, match="leaks"):
        Fold(name="naive", train_end="2025-03", eval_start="2025-04", eval_end="2026-03")


def test_a_fold_with_a_too_small_embargo_is_refused():
    """Five months of gap is still one month of shared labels. Off-by-one here is silent."""
    with pytest.raises(ValueError, match="leaks"):
        Fold(name="nearly", train_end="2024-11", eval_start="2025-04", eval_end="2026-03")


def test_the_smallest_safe_embargo_is_accepted():
    fold = Fold(name="exact", train_end="2024-10", eval_start="2025-04", eval_end="2026-03")
    assert len(fold.embargoed) == LABEL_HORIZON_MONTHS - 1


def test_the_refusal_says_what_to_do_about_it():
    """An error that only says "that leaks" sends someone guessing at the number."""
    with pytest.raises(ValueError, match="Move train_end back to 2024-10"):
        Fold(name="naive", train_end="2025-03", eval_start="2025-04", eval_end="2026-03")


def test_a_backwards_evaluation_range_is_refused():
    with pytest.raises(ValueError, match="precedes"):
        Fold(name="backwards", train_end="2023-01", eval_start="2024-06", eval_end="2024-01")


def test_the_embargoed_months_are_named_not_implied():
    """So the cost shows up in a log rather than hiding behind two dates that look adjacent."""
    fold = Fold(name="t", train_end="2024-10", eval_start="2025-04", eval_end="2026-03")
    assert fold.embargoed == ("2024-11", "2024-12", "2025-01", "2025-02", "2025-03")


# ------------------------------------------------------------------ no label overlap, proven


def all_label_months(cutoffs, horizon=LABEL_HORIZON_MONTHS):
    """Every month that any of these cutoffs' labels is about."""
    months = set()
    for cutoff in cutoffs:
        start, end = label_window(cutoff, horizon)
        months.update(
            shift_month(start, offset) for offset in range(months_between(start, end) + 1)
        )
    return months


def cutoffs_up_to(end, start="2017-09"):
    return [shift_month(start, offset) for offset in range(months_between(start, end) + 1)]


def test_no_training_label_month_is_also_an_evaluation_label_month():
    """The property the embargo is for, asserted directly on label windows rather than on dates."""
    _, test = protocol("2026-03")
    training = all_label_months(cutoffs_up_to(test.train_end))
    evaluation = all_label_months(cutoffs_up_to(test.eval_end, test.eval_start))
    assert not (training & evaluation), sorted(training & evaluation)


def test_every_tuning_fold_is_also_clean():
    tuning, _ = protocol("2026-03")
    for fold in tuning:
        training = all_label_months(cutoffs_up_to(fold.train_end))
        evaluation = all_label_months(cutoffs_up_to(fold.eval_end, fold.eval_start))
        assert not (training & evaluation), f"{fold.name}: {sorted(training & evaluation)}"


def test_no_tuning_fold_reaches_into_the_test_periods_labels():
    """Tuning on months the test is scored on would make the test a validation set."""
    tuning, test = protocol("2026-03")
    test_labels = all_label_months(cutoffs_up_to(test.eval_end, test.eval_start))
    for fold in tuning:
        seen = all_label_months(cutoffs_up_to(fold.eval_end))
        assert not (seen & test_labels), f"{fold.name} overlaps the test labels"


# ------------------------------------------------------------------ the protocol's shape


def test_the_tuning_folds_roll_forward_and_never_overlap_each_other():
    tuning, _ = protocol("2026-03")
    assert [fold.name for fold in tuning] == ["validate-1", "validate-2", "validate-3"]
    for earlier, later in zip(tuning, tuning[1:], strict=False):
        assert months_between(earlier.eval_end, later.eval_start) == 1
        assert months_between(earlier.train_end, later.train_end) > 0, "later folds see more data"


def test_the_test_fold_is_the_most_recent_twelve_answerable_cutoffs():
    _, test = protocol("2026-03")
    assert (test.eval_start, test.eval_end) == ("2025-04", "2026-03")
    assert months_between(test.eval_start, test.eval_end) == 11


def test_rolling_folds_are_ordered_oldest_first():
    folds = rolling_folds("2024-09", folds=3)
    starts = [fold.eval_start for fold in folds]
    assert starts == sorted(starts)


def test_the_final_fit_recovers_the_months_tuning_held_back():
    """Those months were withheld to choose hyperparameters, not because they are tainted.
    Dropping a year of the most recent data from the final fit would be a self-inflicted
    handicap."""
    tuning, test = protocol("2026-03")
    assert months_between(tuning[-1].train_end, final_training_end(test)) > 0
    assert final_training_end(test) == test.train_end


# ------------------------------------------------------------------ splitting rows


def test_splitting_puts_the_embargo_in_neither_set():
    frame = pd.DataFrame({"as_of_month": ["2024-09", "2024-10", "2025-01", "2025-04", "2026-03"]})
    fold = Fold(name="t", train_end="2024-10", eval_start="2025-04", eval_end="2026-03")
    training, evaluation = split(frame, fold)
    assert list(training["as_of_month"]) == ["2024-09", "2024-10"]
    assert list(evaluation["as_of_month"]) == ["2025-04", "2026-03"]
    kept = set(training["as_of_month"]) | set(evaluation["as_of_month"])
    assert "2025-01" not in kept, "an embargoed cutoff must belong to neither set"


def test_splitting_an_empty_frame_gives_two_empty_frames():
    frame = pd.DataFrame({"as_of_month": pd.Series([], dtype="object")})
    fold = Fold(name="t", train_end="2024-10", eval_start="2025-04", eval_end="2026-03")
    training, evaluation = split(frame, fold)
    assert len(training) == len(evaluation) == 0


# ------------------------------------------------------------------ against the real warehouse


@pytest.mark.integration
def test_the_protocol_splits_the_real_mart_as_expected(gold_available):
    """Pins the protocol's shape to the live data, so a rebuilt mart that shifts the test window
    shows up here rather than in a model comparison months later."""
    from drugwatch_ml import features

    frame = features.load_features()
    tuning, test = protocol(str(frame["as_of_month"].max()))
    training, test_rows = split(frame, test)

    assert len(tuning) == 3
    assert not set(training["as_of_month"]) & set(test_rows["as_of_month"])
    # Every embargoed cutoff is genuinely in neither set.
    for cutoff in test.embargoed:
        assert cutoff not in set(training["as_of_month"])
        assert cutoff not in set(test_rows["as_of_month"])
    # And the embargo really does cost something, so nobody can think it is free.
    assert len(frame[frame["as_of_month"].isin(test.embargoed)]) > 1000


@pytest.mark.integration
def test_the_test_set_is_mostly_companies_the_model_never_trained_on(gold_available):
    """Recorded as a test because it is the single biggest limitation of this score, and the kind
    of fact that quietly stops being true when the archive grows. Step 5 must report the two
    groups separately; if this ratio ever collapses, that requirement can be revisited."""
    from drugwatch_ml import features

    frame = features.load_features()
    _, test = protocol(str(frame["as_of_month"].max()))
    training, test_rows = split(frame, test)

    known = set(training["manufacturer_id"])
    new_companies = test_rows[~test_rows["manufacturer_id"].isin(known)]
    share = new_companies["manufacturer_id"].nunique() / test_rows["manufacturer_id"].nunique()
    assert 0.3 < share < 0.7, f"{share:.0%} of test companies are new - the split's shape changed"
