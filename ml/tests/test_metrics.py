"""The metrics, and the two places the obvious implementation gives a different answer."""

import numpy as np
import pandas as pd
import pytest

from drugwatch_ml.metrics import (
    bootstrap_difference,
    evaluate,
    pr_auc,
    precision_at_k,
    precision_at_k_by_month,
    roc_auc,
)


def test_a_perfect_ranking_scores_one_and_a_reversed_one_scores_zero():
    labels = [0, 0, 1, 1]
    assert roc_auc(labels, [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert roc_auc(labels, [0.9, 0.8, 0.2, 0.1]) == 0.0


def test_pr_auc_floor_is_the_positive_rate_not_a_half():
    """The number PR-AUC must be compared against. A random ranking scores ROC-AUC 0.5 but PR-AUC
    ~ the positive rate, so reading PR-AUC against 0.5 makes every model look broken."""
    generator = np.random.default_rng(0)
    labels = (generator.random(20_000) < 0.13).astype(int)
    random_scores = generator.random(20_000)
    assert pr_auc(labels, random_scores) == pytest.approx(0.13, abs=0.02)
    assert roc_auc(labels, random_scores) == pytest.approx(0.5, abs=0.02)


# ------------------------------------------------------------------ precision@k per month


def test_precision_at_k_takes_the_top_k_only():
    labels = [1, 1, 0, 0, 0]
    scores = [0.9, 0.8, 0.7, 0.6, 0.5]
    assert precision_at_k(labels, scores, k=2) == 1.0
    assert precision_at_k(labels, scores, k=4) == 0.5


def test_precision_at_k_handles_fewer_rows_than_k():
    assert precision_at_k([1, 0], [0.9, 0.1], k=20) == 0.5


def test_the_per_month_average_differs_from_pooling_everything():
    """Why the metric is defined per month. Pooled, the busy month's rows fill the top 20 and the
    quiet month is never represented - but a list is read one month at a time."""
    frame = pd.DataFrame({"as_of_month": ["2025-01"] * 4 + ["2025-02"] * 4})
    labels = [1, 1, 1, 1, 0, 0, 0, 1]
    # January's scores are all higher, so pooling hands the whole top-4 to January.
    scores = [0.99, 0.98, 0.97, 0.96, 0.4, 0.3, 0.2, 0.1]

    pooled = precision_at_k(labels, scores, k=4)
    per_month = precision_at_k_by_month(frame, labels, scores, k=4)
    assert pooled == 1.0
    assert per_month == 0.625, "January 1.0 and February 0.25, averaged"
    assert pooled != per_month


def test_each_month_is_weighted_equally_not_by_its_size():
    """A month with 1,500 rows and a month with 40 both produce one list, so both count once."""
    frame = pd.DataFrame({"as_of_month": ["2025-01"] * 100 + ["2025-02"] * 4})
    labels = [0] * 100 + [1, 1, 1, 1]
    scores = list(np.linspace(1, 0.5, 100)) + [0.4, 0.3, 0.2, 0.1]
    assert precision_at_k_by_month(frame, labels, scores, k=4) == 0.5


# ------------------------------------------------------------------ the company-level bootstrap


def company_frame(companies_with_many_rows: int = 5, rows_each: int = 20):
    """One company repeated many times, plus singletons - the real shape of this data."""
    companies, labels, good, bad = [], [], [], []
    generator = np.random.default_rng(7)
    for company in range(companies_with_many_rows):
        label = company % 2
        for _ in range(rows_each):
            companies.append(f"repeat-{company}")
            labels.append(label)
            good.append(label + generator.normal(0, 0.3))
            bad.append(generator.normal(0, 1))
    for single in range(40):
        label = single % 2
        companies.append(f"one-{single}")
        labels.append(label)
        good.append(label + generator.normal(0, 0.3))
        bad.append(generator.normal(0, 1))
    frame = pd.DataFrame({"manufacturer_id": companies, "as_of_month": "2025-01"})
    return frame, np.array(labels), np.array(good), np.array(bad)


def test_resampling_companies_gives_a_wider_interval_than_resampling_rows():
    """The reason the bootstrap is grouped. One manufacturer contributes up to 12 monthly rows and
    those are one company's history seen twelve times, not twelve independent cases. Resampling
    rows pretends otherwise and reports an interval the evidence does not support - which is how a
    model gets called "significantly better" when it is not."""
    frame, labels, good, bad = company_frame()

    _, grouped_low, grouped_high = bootstrap_difference(frame, labels, good, bad, draws=400)
    grouped_width = grouped_high - grouped_low

    # The same bootstrap with every row treated as its own company.
    rows = frame.assign(manufacturer_id=[f"row-{i}" for i in range(len(frame))])
    _, row_low, row_high = bootstrap_difference(rows, labels, good, bad, draws=400)
    row_width = row_high - row_low

    assert grouped_width > row_width, (
        f"grouped CI {grouped_width:.3f} should be wider than row-level {row_width:.3f}; "
        "if it is not, the grouping is not taking effect"
    )


def test_the_difference_itself_is_not_affected_by_the_grouping():
    """Only the interval should change - the point estimate is the same number either way."""
    frame, labels, good, bad = company_frame()
    grouped, _, _ = bootstrap_difference(frame, labels, good, bad, draws=50)
    assert grouped == pytest.approx(pr_auc(labels, good) - pr_auc(labels, bad))


def test_an_interval_including_zero_means_no_claim_can_be_made():
    """Two equally useless scores must not come out 'significantly different'."""
    frame, labels, _, bad = company_frame()
    generator = np.random.default_rng(1)
    other_noise = generator.normal(0, 1, len(labels))
    _, lower, upper = bootstrap_difference(frame, labels, bad, other_noise, draws=400)
    assert lower < 0 < upper


def test_the_bootstrap_is_reproducible():
    frame, labels, good, bad = company_frame()
    first = bootstrap_difference(frame, labels, good, bad, draws=100, seed=42)
    second = bootstrap_difference(frame, labels, good, bad, draws=100, seed=42)
    assert first == second


# ------------------------------------------------------------------ the result object


def test_evaluate_reports_companies_not_just_rows():
    """Because 22,070 test rows are only 2,242 companies, and the second number is the one that
    bounds how much the evidence actually supports."""
    frame = pd.DataFrame({"manufacturer_id": ["a", "a", "b", "b"], "as_of_month": ["2025-01"] * 4})
    result = evaluate("t", frame, [0, 1, 0, 1], [0.1, 0.9, 0.2, 0.8], k=2)
    assert (result.rows, result.companies) == (4, 2)
    assert result.positive_rate == 0.5
    assert "roc_auc" in result.as_metrics()
