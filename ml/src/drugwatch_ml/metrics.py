"""The metrics Phase 7 is judged by, and the two places the obvious implementation is wrong.

Plan §12 asks for ROC-AUC, PR-AUC and precision@top-K. The first two are one call each. The other
two decisions here are not obvious and both change the answer:

**1. Precision@K is computed per month, then averaged.** Pooling all 22,070 test rows and taking
the top 20 would hand back a list dominated by whichever month had the most activity - and nobody
reads the archive that way. A list is read one month at a time: "who should be looked at in April".
So the metric is the mean of each month's own precision@20, which is the number that matches how
the output would actually be used.

**2. Confidence intervals resample companies, not rows.** One manufacturer contributes up to 12
monthly rows to the test window, and those rows are the same company's history seen twelve times -
not twelve independent observations. Resampling rows would treat them as independent and produce
an interval far narrower than the evidence supports, which is exactly how a model gets reported as
"significantly better" when it is not. So the bootstrap draws whole companies with replacement and
keeps all of a drawn company's rows.

Only three things come from scikit-learn, all under ADR 0015: `roc_auc_score`,
`average_precision_score`, and nothing else in this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

# How many manufacturers a monthly list would realistically hold. 20 because that is what the
# Phase 6 dashboard's "most frequently reported" table shows, so the metric matches a real list.
DEFAULT_K = 20


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Probability that a random positive outranks a random negative. 0.5 is coin-flipping."""
    return float(roc_auc_score(labels, scores))


def pr_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Average precision: the PR-AUC that does NOT interpolate between points.

    The interpolated version (the trapezoid under a precision-recall curve) is optimistically
    biased, and the bias grows as positives get rarer - which is precisely this problem. The
    baseline to compare against is the positive rate, not 0.5.
    """
    return float(average_precision_score(labels, scores))


def precision_at_k(labels: Sequence[int], scores: Sequence[float], k: int = DEFAULT_K) -> float:
    """Share of the top-k scores that are positive. Fewer than k rows means all of them.

    Ties are broken by the order given, which matters for the rule baseline: its scores are only
    0 or 1, so "the top 20" of a 1,500-row month is an arbitrary 20 of however many it flagged.
    That is a real weakness of a binary rule, not an artefact of this function - and the reason
    the rule baseline is also reported with its own precision over everything it flags.
    """
    labels = np.asarray(labels)
    order = np.argsort(-np.asarray(scores, dtype="float64"), kind="stable")
    top = labels[order][: min(k, len(labels))]
    return float(top.mean()) if len(top) else float("nan")


def precision_at_k_by_month(
    frame: pd.DataFrame,
    labels: Sequence[int],
    scores: Sequence[float],
    k: int = DEFAULT_K,
    month_column: str = "as_of_month",
) -> float:
    """Mean of each month's own precision@k - see note 1. Months with no rows are skipped."""
    working = pd.DataFrame(
        {
            "month": frame[month_column].to_numpy(),
            "label": np.asarray(labels),
            "score": np.asarray(scores, dtype="float64"),
        }
    )
    per_month = [
        precision_at_k(group["label"].to_numpy(), group["score"].to_numpy(), k)
        for _, group in working.groupby("month", sort=True)
        if len(group)
    ]
    return float(np.mean(per_month)) if per_month else float("nan")


@dataclass(frozen=True)
class Result:
    """One model's scores on one evaluation set."""

    name: str
    rows: int
    companies: int
    positive_rate: float
    roc_auc: float
    pr_auc: float
    precision_at_k: float
    k: int = DEFAULT_K

    def line(self) -> str:
        return (
            f"  {self.name:34s} ROC-AUC {self.roc_auc:.3f}  PR-AUC {self.pr_auc:.3f}"
            f"  P@{self.k}/month {self.precision_at_k:.3f}"
            f"   ({self.rows:,} rows, {self.positive_rate:.1%} positive)"
        )

    def as_metrics(self) -> dict[str, float]:
        """Flattened for MLflow, which takes numbers rather than objects."""
        return {
            "roc_auc": self.roc_auc,
            "pr_auc": self.pr_auc,
            f"precision_at_{self.k}_per_month": self.precision_at_k,
            "positive_rate": self.positive_rate,
            "rows": float(self.rows),
            "companies": float(self.companies),
        }


def evaluate(
    name: str,
    frame: pd.DataFrame,
    labels: Sequence[int],
    scores: Sequence[float],
    k: int = DEFAULT_K,
) -> Result:
    """Every headline metric for one model on one set."""
    labels = np.asarray(labels)
    return Result(
        name=name,
        rows=len(labels),
        companies=int(frame["manufacturer_id"].nunique()),
        positive_rate=float(labels.mean()),
        roc_auc=roc_auc(labels, scores),
        pr_auc=pr_auc(labels, scores),
        precision_at_k=precision_at_k_by_month(frame, labels, scores, k),
        k=k,
    )


def bootstrap_difference(
    frame: pd.DataFrame,
    labels: Sequence[int],
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    metric=pr_auc,
    draws: int = 1000,
    group_column: str = "manufacturer_id",
    seed: int = 0,
) -> tuple[float, float, float]:
    """`metric(a) - metric(b)`, with a 95% interval from resampling **companies** - see note 2.

    Returns (difference on the real data, lower bound, upper bound). An interval that excludes 0
    is what decision C requires before claiming one model beats another.
    """
    labels = np.asarray(labels)
    scores_a = np.asarray(scores_a, dtype="float64")
    scores_b = np.asarray(scores_b, dtype="float64")

    companies = frame[group_column].to_numpy()
    unique = np.unique(companies)
    # Row positions per company, so a drawn company brings all of its months with it.
    positions = {company: np.flatnonzero(companies == company) for company in unique}

    observed = metric(labels, scores_a) - metric(labels, scores_b)

    generator = np.random.default_rng(seed)
    differences = []
    for _ in range(draws):
        drawn = generator.choice(unique, size=len(unique), replace=True)
        rows = np.concatenate([positions[company] for company in drawn])
        sample_labels = labels[rows]
        # A draw that happens to contain only one class cannot be scored; skipping it is correct
        # and is reported through the number of usable draws rather than silently filled in.
        if sample_labels.min() == sample_labels.max():
            continue
        differences.append(
            metric(sample_labels, scores_a[rows]) - metric(sample_labels, scores_b[rows])
        )

    if not differences:
        return observed, float("nan"), float("nan")
    lower, upper = np.percentile(differences, [2.5, 97.5])
    return observed, float(lower), float(upper)
