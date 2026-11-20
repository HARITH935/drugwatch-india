"""The LightGBM risk model, and what it is deliberately not told.

Plan §6 mandates LightGBM and plan §9 step 5 says "train LightGBM; tune key hyperparameters".
What is worth knowing about this wrapper is the three things it does differently from the logistic
baseline, each for a reason:

**1. Nulls go in untouched.** A share is null when the window held no findings to divide - absence,
not 0% (`mart_ml_features`). The logistic baseline has to fill those with a training median because
a linear model cannot represent "missing". LightGBM learns which side of each split a missing value
belongs on, so filling them would be throwing away the distinction between "no reports at all" and
"reports, none of them an assay failure". They are different states and the model is allowed to
see that.

**2. No scaling.** Trees split on thresholds, so units do not compete; scaling would be noise in
the code and nothing in the model.

**3. Imbalance is a tuned choice, not a default.** With 12-13% positives, `scale_pos_weight`
usually lifts ranking metrics a little - and it distorts the predicted probabilities, which §4.3
shows to the public as a probability. So it is searched over rather than assumed, and if a
reweighted model wins, step 5's calibration check is what decides whether its output may be called
a probability at all.
"""

from dataclasses import asdict, dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

from drugwatch_ml.features import FEATURE_COLUMNS, LABEL_COLUMN


@dataclass(frozen=True)
class Settings:
    """One point in the hyperparameter space, with LightGBM's defaults as the starting point.

    `n_estimators` is searched rather than found by early stopping, on purpose: early stopping
    would read the fold's own evaluation rows to choose the tree count and then those same rows
    would score the trial, making every validation number slightly optimistic. Searching it keeps
    the validation folds doing exactly one job.
    """

    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_child_samples: int = 20
    feature_fraction: float = 1.0
    bagging_fraction: float = 1.0
    bagging_freq: int = 0
    lambda_l2: float = 0.0
    scale_pos_weight: float = 1.0

    def as_params(self) -> dict:
        return {
            "objective": "binary",
            "n_estimators": self.n_estimators,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_child_samples": self.min_child_samples,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "lambda_l2": self.lambda_l2,
            "scale_pos_weight": self.scale_pos_weight,
            "verbose": -1,  # LightGBM is chatty about feature-fraction rounding on every fit
            "n_jobs": -1,
            "deterministic": True,
            "random_state": 0,
        }

    def as_tags(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


class RiskModel:
    """Fit on a training frame, score any frame with the same columns."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.model: lgb.LGBMClassifier | None = None

    def fit(self, train: pd.DataFrame) -> "RiskModel":
        self.model = lgb.LGBMClassifier(**self.settings.as_params())
        # No imputation and no scaling - see notes 1 and 2.
        self.model.fit(train[list(FEATURE_COLUMNS)], train[LABEL_COLUMN].to_numpy())
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        """Predicted probability of being reported in the next 6 months."""
        if self.model is None:
            raise RuntimeError("fit() must run before scoring")
        return self.model.predict_proba(frame[list(FEATURE_COLUMNS)])[:, 1]

    def importances(self) -> pd.Series:
        """LightGBM's own gain-based importance. Step 6 replaces this with SHAP, which attributes
        individual predictions - this is only a sanity check that the model used more than one
        column."""
        if self.model is None:
            raise RuntimeError("fit() must run before reading importances")
        return pd.Series(
            self.model.booster_.feature_importance(importance_type="gain"),
            index=list(FEATURE_COLUMNS),
        ).sort_values(ascending=False)
