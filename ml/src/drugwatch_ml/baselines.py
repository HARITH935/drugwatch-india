"""The three baselines LightGBM has to beat, and why there are three rather than the plan's two.

Plan §12 names two: the rule "reported in the last N months -> will be reported again", and
logistic regression. Measured during planning (2026-11-20), the rule scores **ROC-AUC 0.623** on
the test window - while simply ranking manufacturers by how many findings they already have over
24 months scores **0.687**. The free one-column ranking beats the plan's own baseline.

That matters because "beats both baselines" could then be satisfied by a model that is worse than
a `count(*)`. So the count ranking is a third baseline and decision C (2026-11-20) raised the bar:
LightGBM must beat all three on PR-AUC with a confidence interval excluding no difference.

A note on what each one is for:

- **`reported_recently`** is the operational straw man: what anyone would do without a model. It
  returns 0 or 1, which makes it strong on recall and useless for ranking - and that limitation is
  the point of including it.
- **`reports_24m_ranking`** is the honest "do you even need a model" test. One column, no fitting.
- **`LogisticBaseline`** is the plan's statistical baseline: every feature, linear, no interactions.
  It answers "is the signal here non-linear, or did a linear model have it all along?"
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from drugwatch_ml.features import FEATURE_COLUMNS, LABEL_COLUMN


def reported_recently(frame: pd.DataFrame) -> np.ndarray:
    """Plan §12 baseline 1: anything reported in the last 6 months is predicted to recur.

    Returns 0.0/1.0 rather than a probability, deliberately - this is a rule, and reporting it as
    if it ranked manufacturers would flatter it.
    """
    return (frame["reports_6m"].to_numpy(dtype="float64") > 0).astype("float64")


def reports_24m_ranking(frame: pd.DataFrame) -> np.ndarray:
    """Baseline 3: rank by findings in the last 24 months. No fitting, one column."""
    return frame["reports_24m"].to_numpy(dtype="float64")


class LogisticBaseline:
    """Plan §12 baseline 2: logistic regression over every feature.

    Two compromises a linear model needs and LightGBM does not, both stated because they are the
    reason this baseline is not simply "the same model, linear":

    - **Missing values must be filled.** A share is null when the window held no findings to
      divide - absence, not 0% - and `LogisticRegression` cannot accept that. Filled with the
      *training* median (never the evaluation set's, which would leak), and the median is stored at
      fit time. LightGBM takes nulls natively and learns which side of a split they belong on, so
      it is told nothing here.
    - **Features must be scaled**, or the optimiser weights `reports_24m` (0-300) and
      `assay_share_12m` (0-1) by their units. Scaler fitted on training rows only.

    Filled with pandas rather than scikit-learn's imputer on purpose: ADR 0015 approved
    `LogisticRegression`, `StandardScaler` and two metric functions, and a fourth class would be a
    wider dependency than was agreed for two lines of `fillna`.
    """

    def __init__(self, max_iterations: int = 2000, seed: int = 0) -> None:
        self.scaler = StandardScaler()
        self.model = LogisticRegression(
            max_iter=max_iterations,
            # Rare positives (12.8% in training): without this the fit spends its effort on the
            # majority class and the ranking suffers, which would make the baseline weaker than
            # the plan intends it to be.
            class_weight="balanced",
            random_state=seed,
        )
        self.medians: pd.Series | None = None

    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        if self.medians is None:
            raise RuntimeError("fit() must run before scoring: the medians come from training")
        filled = frame[list(FEATURE_COLUMNS)].astype("float64").fillna(self.medians)
        # A column that is entirely null in training leaves a null median, which would survive
        # fillna and reach the model as NaN. Zero is the right answer there and it is explicit.
        return filled.fillna(0.0).to_numpy()

    def fit(self, train: pd.DataFrame) -> "LogisticBaseline":
        self.medians = train[list(FEATURE_COLUMNS)].astype("float64").median()
        matrix = self.scaler.fit_transform(self._matrix(train))
        self.model.fit(matrix, train[LABEL_COLUMN].to_numpy())
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        """Predicted probability of being reported in the next 6 months."""
        return self.model.predict_proba(self.scaler.transform(self._matrix(frame)))[:, 1]

    def coefficients(self) -> pd.Series:
        """What the linear model leaned on, largest absolute weight first. Comparable across
        features because the inputs were scaled."""
        return pd.Series(self.model.coef_[0], index=list(FEATURE_COLUMNS)).sort_values(
            key=abs, ascending=False
        )


def score_all(train: pd.DataFrame, evaluate_on: pd.DataFrame) -> dict[str, Sequence[float]]:
    """Every baseline's scores for one fold. The two rules ignore `train` - they have nothing to
    fit, which is exactly what makes them baselines."""
    return {
        "rule: reported in last 6m": reported_recently(evaluate_on),
        "ranking: reports in last 24m": reports_24m_ranking(evaluate_on),
        "logistic regression": LogisticBaseline().fit(train).score(evaluate_on),
    }
