"""Time-based splits with an embargo, and the leakage each guard exists to stop.

Plan §12: *"rolling time-based splits (train on earlier cutoffs, test on later ones). No random
splits."* The rolling part is easy. The part that a plain date split gets wrong is the **embargo**,
and it is worth being precise about, because nothing fails loudly when it is missing.

**The leak.** Every row is a manufacturer at a monthly cutoff. Its features use months up to and
including the cutoff; its label is "was this manufacturer reported in the following 6 months". So a
row's label is not a fact about its cutoff - it is a fact about the **6 months after** it.

Take a training row at cutoff 2025-03 and a test row at cutoff 2025-04:

    training row   features: ... 2025-03 | label: 2025-04 .. 2025-09
    test row       features: ... 2025-04 | label: 2025-05 .. 2025-10
                                           ^^^^^^^^^^^^^^^^^^^^^^^^ five shared months

Five of the six months the test is scored on were already used as training *answers*. The model is
not being tested on an unseen future; it is being tested on a future it was partly told about. A
split on the cutoff date alone looks completely clean and hides this entirely.

**The fix** is to drop ("purge") every training cutoff whose label window reaches into the
evaluation period's label window. With a 6-month horizon that means the last training cutoff must
be at least 6 months before the first evaluation cutoff, so the 5 cutoffs in between are discarded.
They are a real cost - about 9,000 rows - and paying it is the point.

**What is deliberately NOT treated as leakage:** the same manufacturer appearing in both the
training and the evaluation set, at different cutoffs. The task is whether a company **already in
the archive** gets reported again, so its own history is the signal, not contamination. What that
overlap does break is the arithmetic of confidence intervals - one company's 12 monthly rows are
not 12 independent observations - which is why step 5 resamples whole companies rather than rows.
"""

from dataclasses import dataclass

import pandas as pd

# The label's horizon, fixed by the mart that computed it (mart_ml_features.sql) and therefore not
# a parameter here: changing it means rebuilding the label in dbt, not passing a different number.
LABEL_HORIZON_MONTHS = 6


def shift_month(month: str, by: int) -> str:
    """Move a 'YYYY-MM' cutoff by whole months. Month arithmetic, not day arithmetic: adding 30
    days to a cutoff lands in the wrong month twice a year."""
    year, month_number = (int(part) for part in month.split("-"))
    index = year * 12 + (month_number - 1) + by
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def months_between(start: str, end: str) -> int:
    """How many months from `start` to `end`, signed."""
    start_year, start_month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    return (end_year * 12 + end_month) - (start_year * 12 + start_month)


def label_window(cutoff: str, horizon: int = LABEL_HORIZON_MONTHS) -> tuple[str, str]:
    """The months a cutoff's label is actually about: the `horizon` months after it."""
    return shift_month(cutoff, 1), shift_month(cutoff, horizon)


@dataclass(frozen=True)
class Fold:
    """One time-based split: train on cutoffs up to `train_end`, evaluate on the range after it.

    Refuses to exist if the embargo is too small, rather than being checked by a caller who might
    forget. A Fold that cannot leak is easier to reason about than a Fold plus a convention.
    """

    name: str
    train_end: str
    eval_start: str
    eval_end: str
    horizon: int = LABEL_HORIZON_MONTHS

    def __post_init__(self) -> None:
        if months_between(self.eval_start, self.eval_end) < 0:
            raise ValueError(f"{self.name}: eval_end {self.eval_end} precedes {self.eval_start}")
        gap = months_between(self.train_end, self.eval_start)
        if gap < self.horizon:
            # The exact condition: the last training label month must be strictly before the first
            # evaluation label month, i.e. train_end + horizon < eval_start + 1.
            raise ValueError(
                f"{self.name}: training ends {self.train_end} and evaluation starts"
                f" {self.eval_start}, a gap of {gap} month(s). With a {self.horizon}-month label"
                f" horizon that leaks: training labels cover"
                f" {label_window(self.train_end, self.horizon)[0]}.."
                f"{label_window(self.train_end, self.horizon)[1]} and evaluation labels start"
                f" {label_window(self.eval_start, self.horizon)[0]}."
                f" Move train_end back to {shift_month(self.eval_start, -self.horizon)} or earlier."
            )

    @property
    def embargoed(self) -> tuple[str, ...]:
        """The cutoffs thrown away between training and evaluation. Named so the cost is visible
        in logs rather than implied by two dates that look adjacent."""
        first = shift_month(self.train_end, 1)
        count = months_between(first, self.eval_start)
        return tuple(shift_month(first, offset) for offset in range(count))

    def describe(self) -> str:
        return (
            f"{self.name}: train <= {self.train_end} | embargo {len(self.embargoed)} month(s)"
            f" | evaluate {self.eval_start}..{self.eval_end}"
        )


def split(
    frame: pd.DataFrame, fold: Fold, column: str = "as_of_month"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The two row sets for a fold.

    Everything inside the embargo belongs to neither set, by construction rather than by filter.
    """
    cutoffs = frame[column]
    training = frame[cutoffs <= fold.train_end]
    evaluation = frame[(cutoffs >= fold.eval_start) & (cutoffs <= fold.eval_end)]
    return training, evaluation


def rolling_folds(
    last_cutoff: str,
    *,
    folds: int = 3,
    eval_months: int = 6,
    horizon: int = LABEL_HORIZON_MONTHS,
) -> tuple[Fold, ...]:
    """Rolling-origin folds for tuning, oldest first, ending before `last_cutoff`.

    Each fold trains on everything up to its own embargo and evaluates on the `eval_months` that
    follow - so later folds train on more data, which is what actually happens in production. The
    folds are built backwards from `last_cutoff` so that the most recent tuning fold sits as close
    to the real test period as the embargo allows, without ever touching it.
    """
    built = []
    eval_end = last_cutoff
    for index in range(folds):
        eval_start = shift_month(eval_end, -(eval_months - 1))
        built.append(
            Fold(
                name=f"validate-{folds - index}",
                train_end=shift_month(eval_start, -horizon),
                eval_start=eval_start,
                eval_end=eval_end,
                horizon=horizon,
            )
        )
        eval_end = shift_month(eval_start, -1)
    return tuple(reversed(built))


def protocol(
    newest_labelled_cutoff: str,
    *,
    test_months: int = 12,
    tuning_folds: int = 3,
    eval_months: int = 6,
    horizon: int = LABEL_HORIZON_MONTHS,
) -> tuple[tuple[Fold, ...], Fold]:
    """The whole protocol: the tuning folds, and the single test fold.

    The test fold is the most recent `test_months` cutoffs whose label the archive can answer. It
    is evaluated **once**. Everything that tunes anything - hyperparameters, thresholds, which
    model to prefer - uses only the tuning folds, which all end before the test fold's embargo.
    That is the same rule CLAUDE.md §5 sets for the LLM eval set's test split, for the same reason:
    a test set you fit against is a training set with a flattering name.
    """
    test_start = shift_month(newest_labelled_cutoff, -(test_months - 1))
    test = Fold(
        name="test",
        train_end=shift_month(test_start, -horizon),
        eval_start=test_start,
        eval_end=newest_labelled_cutoff,
        horizon=horizon,
    )
    # Tuning must not reach into the test fold's label window either, so the newest cutoff any
    # tuning fold may evaluate is one month before the test fold's own training cutoff.
    tuning_last = shift_month(test.train_end, -1)
    return rolling_folds(
        tuning_last, folds=tuning_folds, eval_months=eval_months, horizon=horizon
    ), test


def final_training_end(test: Fold) -> str:
    """Where the model that gets tested is allowed to train up to.

    After tuning picks the settings, the model is refit on **everything** before the test embargo -
    including the months the tuning folds held back. Those months were withheld to choose
    hyperparameters, not because they are tainted, and throwing away a year of the most recent data
    in the final fit would be a self-inflicted handicap.
    """
    return test.train_end
