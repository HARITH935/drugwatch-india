"""The ONNX conversion check, and the tie-sensitivity trap it was written to avoid."""

import numpy as np
import pytest

from drugwatch_serving.onnx_export import (
    DISPLAY_TOLERANCE,
    inverted_rows,
    top_k_identical,
    verify,
)


def test_an_identical_model_agrees_perfectly():
    scores = np.array([0.1, 0.4, 0.2, 0.9, 0.5])
    agreement = verify(scores, scores.copy())
    assert agreement.max_absolute_difference == 0.0
    assert agreement.inverted_rows == 0
    assert agreement.order_preserved
    assert agreement.top_20_identical
    assert agreement.within_display_tolerance


def test_float32_rounding_is_not_treated_as_a_broken_export():
    """The real situation. ONNX runs tree ensembles in float32 while LightGBM accumulates in
    float64, so predictions differ by ~1e-7. Nothing a reader sees changes at that size."""
    scores = np.array([0.1, 0.4, 0.2, 0.9, 0.5])
    agreement = verify(scores, scores + 1e-7)
    assert agreement.order_preserved
    assert agreement.within_display_tolerance


def test_ties_broken_differently_are_not_an_inversion():
    """The bug this replaced. Comparing `argsort` outputs calls this a changed ranking: the
    original ties and a stable sort keeps input order, while 1e-9 in the converted model orders
    them. Measured on the real test window, an argsort comparison reported a differing ranking at
    0 actual inversions and Spearman 1.000000."""
    original = np.array([0.5, 0.5, 0.5, 0.2])
    converted = np.array([0.5 + 1e-9, 0.5, 0.5 - 1e-9, 0.2])

    # the old, wrong check would have failed here
    assert not np.array_equal(
        np.argsort(original, kind="stable"), np.argsort(converted, kind="stable")
    )
    # the right one passes
    assert inverted_rows(original, converted) == 0
    assert verify(original, converted).order_preserved


def test_a_genuine_swap_is_caught():
    """Two rows the original ranked strictly, in the wrong order after conversion."""
    original = np.array([0.1, 0.2, 0.3])
    converted = np.array([0.1, 0.3, 0.2])  # the last two swapped
    assert inverted_rows(original, converted) == 1
    assert not verify(original, converted).order_preserved


def test_a_fully_reversed_ranking_is_caught_loudly():
    original = np.array([0.1, 0.2, 0.3, 0.4])
    agreement = verify(original, original[::-1].copy())
    # 3, not 6: this counts rows that moved below an earlier group's maximum, not inverted pairs.
    # Zero in the same cases, which is the property `order_preserved` relies on.
    assert agreement.inverted_rows == 3
    assert not agreement.order_preserved
    assert agreement.rank_correlation == pytest.approx(-1.0)


def test_inversions_are_counted_between_tie_groups_not_only_adjacent_ones():
    """A swap can span several tie groups, so tracking only the previous row would miss it."""
    original = np.array([0.1, 0.1, 0.2, 0.2, 0.9])
    converted = np.array([0.1, 0.1, 0.2, 0.2, 0.05])  # the largest becomes the smallest
    # Detected even though the offending row's neighbour is two tie-groups back, which a check
    # that only compared adjacent rows would miss.
    assert inverted_rows(original, converted) == 1
    assert not verify(original, converted).order_preserved


def test_the_top_k_check_compares_sets_not_order():
    """Within a list of 20, the order does not change who is on it."""
    original = np.array([0.9, 0.8, 0.1, 0.2])
    swapped_inside = np.array([0.8, 0.9, 0.1, 0.2])
    assert top_k_identical(original, swapped_inside, k=2)
    different_member = np.array([0.9, 0.05, 0.1, 0.85])
    assert not top_k_identical(original, different_member, k=2)


def test_the_top_k_check_handles_fewer_rows_than_k():
    scores = np.array([0.3, 0.7])
    assert top_k_identical(scores, scores.copy(), k=20)


def test_the_display_tolerance_is_half_the_smallest_shown_unit():
    """A score rendered as "14.2%" cannot be moved by a difference below 0.0005, which is why
    that is the threshold rather than an arbitrary epsilon."""
    assert DISPLAY_TOLERANCE == 5e-4
    scores = np.array([0.1, 0.5])
    assert verify(scores, scores + 4e-4).within_display_tolerance
    assert not verify(scores, scores + 6e-4).within_display_tolerance


def test_spearman_handles_ties_without_scipy():
    """Ranks are averaged within tied groups, as Spearman requires; computed with numpy because
    scipy is only a transitive dependency here (ADR 0015's reasoning)."""
    tied = np.array([0.1, 0.1, 0.3, 0.3, 0.5])
    assert verify(tied, tied.copy()).rank_correlation == pytest.approx(1.0)
