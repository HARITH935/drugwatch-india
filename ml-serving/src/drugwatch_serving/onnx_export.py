"""Convert the registered LightGBM model to ONNX, and prove the conversion did not change it.

Plan §9 Phase 8 steps 1-2. ONNX is a portable format for a trained model: the serving container
runs it with ONNX Runtime and needs no LightGBM, no Python training stack and no model-specific
code. That is the point of the step.

**The conversion is not exact, and the honest thing is to measure the gap rather than assert
equality.** ONNX's tree ensemble runs in float32 while LightGBM accumulates in float64, so
hundreds of leaf values summed in a different precision will not agree to the last bit. What
matters is whether the difference could change a decision: a rank order, or a displayed
percentage. So `verify` reports the largest absolute difference, whether the ranking is identical,
and whether any prediction moves by more than half of the smallest unit anyone will ever see
(0.1 of a percentage point).

`zipmap=False` matters: by default the converter wraps the output in a list of dictionaries, which
is slower and awkward to read, and the service only ever wants the positive class's probability.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxmltools
import onnxruntime
from onnxmltools.convert.common.data_types import FloatTensorType

# Half of the smallest unit a reader will ever see. A score shown as "14.2%" is unaffected by a
# difference below 0.0005, so a gap under this cannot change anything anyone looks at.
DISPLAY_TOLERANCE = 5e-4


@dataclass(frozen=True)
class Agreement:
    """How closely the ONNX model reproduces the original."""

    rows: int
    max_absolute_difference: float
    mean_absolute_difference: float
    rank_correlation: float
    inverted_rows: int
    top_20_identical: bool
    within_display_tolerance: bool

    @property
    def order_preserved(self) -> bool:
        """No row ranks below anything the original placed strictly beneath it.

        Zero here is equivalent to zero inverted *pairs*: if some pair (i, j) with
        original[i] < original[j] had converted[i] > converted[j], then row j would rank below
        something from an earlier group and would be counted. So this is the cheap test for the
        property that matters, and the count itself reports how much moved.
        """
        return self.inverted_rows == 0

    def line(self) -> str:
        return (
            f"  {self.rows:,} rows | max difference {self.max_absolute_difference:.2e}"
            f" | mean {self.mean_absolute_difference:.2e}"
            f" | Spearman {self.rank_correlation:.6f}"
            f" | inverted rows {self.inverted_rows}"
            f" | top-20 set identical: {'yes' if self.top_20_identical else 'NO'}"
            f" | within display tolerance: {'yes' if self.within_display_tolerance else 'NO'}"
        )


def convert(booster, feature_count: int, path: Path) -> Path:
    """Write the ONNX model. One float32 input of shape (any rows, feature_count)."""
    initial_types = [("features", FloatTensorType([None, feature_count]))]
    onnx_model = onnxmltools.convert_lightgbm(
        booster,
        initial_types=initial_types,
        # Without this the output is a list of {label: probability} dicts - slower, and it hides
        # which column is the positive class behind a string key.
        zipmap=False,
        target_opset=None,
    )
    path.write_bytes(onnx_model.SerializeToString())
    return path


def session(path: Path) -> onnxruntime.InferenceSession:
    """An ONNX Runtime session pinned to the CPU provider, which is what the container has."""
    return onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def predict(runtime: onnxruntime.InferenceSession, matrix: np.ndarray) -> np.ndarray:
    """Positive-class probabilities from the ONNX model.

    float32 is not a choice: the graph declares a float32 input, and handing it float64 fails at
    the boundary rather than converting silently.
    """
    inputs = {runtime.get_inputs()[0].name: matrix.astype(np.float32)}
    outputs = runtime.run(None, inputs)
    # With zipmap=False the second output is the probability matrix; column 1 is the positive class.
    probabilities = np.asarray(outputs[1])
    return probabilities[:, 1] if probabilities.ndim == 2 else probabilities.ravel()


def inverted_rows(original: np.ndarray, converted: np.ndarray) -> int:
    """How many rows the conversion moved below something the original ranked strictly beneath.

    A count of rows, not of pairs - cheaper, and zero in exactly the same cases (see
    `Agreement.order_preserved`). A fully reversed ranking of 4 rows reports 3, not 6: three rows
    sit below an earlier group's maximum. The number is a magnitude, not a pair count.

    Comparing `argsort` outputs directly is the obvious check and it is **wrong**: when the
    original gives two rows exactly equal scores, a stable sort keeps them in input order, while a
    difference of 1e-8 in the converted model orders them. That reports a broken export when
    nothing a reader could see has changed. Measured on the real test window: 0 strict inversions
    with Spearman 1.000000, and an `argsort` comparison still said the ranking differed.

    Only strict pairs count. Walking the rows in original order and tracking the largest converted
    value seen in all *earlier* tie-groups makes this O(n log n) rather than comparing 243 million
    pairs.
    """
    order = np.argsort(original, kind="stable")
    original_sorted = original[order]
    converted_sorted = converted[order]

    inversions = 0
    highest_in_earlier_groups = -np.inf
    index = 0
    while index < len(original_sorted):
        group_end = index
        while (
            group_end + 1 < len(original_sorted)
            and original_sorted[group_end + 1] == original_sorted[index]
        ):
            group_end += 1
        group = converted_sorted[index : group_end + 1]
        # Any row here scoring below something from a strictly lower original group is an inversion.
        inversions += int(np.sum(group < highest_in_earlier_groups))
        highest_in_earlier_groups = max(highest_in_earlier_groups, float(group.max()))
        index = group_end + 1
    return inversions


def top_k_identical(original: np.ndarray, converted: np.ndarray, k: int = 20) -> bool:
    """Whether the two models would put the same rows in a top-k list.

    The operational check: precision@20 per month is the metric this project reports, and a list is
    the thing a reader sees. Compared as sets, because the order within a list of 20 does not
    change who is on it.
    """
    size = min(k, len(original))
    return set(np.argsort(-original, kind="stable")[:size]) == set(
        np.argsort(-converted, kind="stable")[:size]
    )


def _ranks(values: np.ndarray) -> np.ndarray:
    """Ranks with ties averaged, which is what Spearman requires."""
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype="float64")
    ranks[order] = np.arange(len(values), dtype="float64")
    # Average the ranks within each group of equal values, or tied scores bias the correlation.
    unique, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    sums = np.zeros(len(unique), dtype="float64")
    np.add.at(sums, inverse, ranks)
    return (sums / counts)[inverse]


def verify(original: np.ndarray, converted: np.ndarray) -> Agreement:
    """Compare the two sets of predictions on the same rows."""
    original = np.asarray(original, dtype="float64")
    converted = np.asarray(converted, dtype="float64")
    differences = np.abs(original - converted)
    # Spearman is Pearson on the ranks, computed here rather than imported: scipy arrives only as
    # a transitive dependency of shap, and ADR 0015's reasoning applies - code should not import
    # what it has not declared, and declaring a whole library for three lines is the worse trade.
    correlation = float(np.corrcoef(_ranks(original), _ranks(converted))[0, 1])
    return Agreement(
        rows=len(original),
        max_absolute_difference=float(differences.max()),
        mean_absolute_difference=float(differences.mean()),
        rank_correlation=correlation,
        inverted_rows=inverted_rows(original, converted),
        top_20_identical=top_k_identical(original, converted, k=20),
        within_display_tolerance=bool(differences.max() < DISPLAY_TOLERANCE),
    )
