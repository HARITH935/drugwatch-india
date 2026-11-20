"""SHAP explanations, and the wording rules they have to obey.

Plan §4.3: *"Each score comes with SHAP explanations ('score is high mainly because of 3 reports
in the last 6 months')"*. Two halves to that, and the second is the harder one.

**The arithmetic.** SHAP splits one prediction into a base value plus one contribution per
feature, and those parts add up exactly - that is the property that makes it an explanation rather
than a ranking of guesses. `additivity_error` checks it on real rows rather than trusting the
library, because a silent mismatch would mean the sentences describe a different prediction from
the one being shown.

**The wording.** These sentences are about named Indian companies on a public site, and CLAUDE.md
§6 is not advisory: a finding applies to one batch, the score reflects *reporting history* rather
than quality, and nothing here may read as an accusation. So the phrasing is built from a fixed
vocabulary (`PHRASES`) instead of being composed from column names, every explanation carries the
reporting-history clause, and a test fails on a list of words that must never appear. A reviewer
can read the whole vocabulary in one screen, which is the point.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from drugwatch_ml.features import FEATURE_COLUMNS
from drugwatch_ml.model import RiskModel

# How each feature is described to a reader. Neutral, factual, and about reporting - never about
# quality, safety or conduct. A feature with no phrase here cannot be explained, which is
# deliberate: a new feature must be given words by a person before it can appear in public text.
PHRASES: dict[str, str] = {
    "reports_3m": "batches reported in the last 3 months",
    "reports_6m": "batches reported in the last 6 months",
    "reports_12m": "batches reported in the last 12 months",
    "reports_24m": "batches reported in the last 24 months",
    "reports_prior_6m": "batches reported in the 6 months before that",
    "reports_trend_6m": "change in batches reported between the last two 6-month periods",
    "months_since_last_report": "months since the most recent reported batch",
    "distinct_drugs_12m": "different products reported in the last 12 months",
    "distinct_reporting_states_12m": "states whose laboratories reported a batch in 12 months",
    "central_lab_reports_12m": "batches reported by central laboratories in the last 12 months",
    "state_lab_reports_12m": "batches reported by state laboratories in the last 12 months",
    "central_lab_share_12m": "share of reports that came from central laboratories",
    "category_mentions_12m": "laboratory test failures named in the last 12 months",
    "assay_share_12m": "share of named test failures that were assay tests",
    "dissolution_share_12m": "share of named test failures that were dissolution tests",
    "sterility_share_12m": "share of named test failures that were sterility tests",
    "description_share_12m": "share of named test failures that were description checks",
    "class_mentions_12m": "medicine-class mentions across reported batches",
    "distinct_drug_classes_12m": "different kinds of medicine reported in the last 12 months",
    "antibiotic_share_12m": "share of reported batches that were antibiotics",
    "analgesic_share_12m": "share of reported batches that were painkillers",
    "gastrointestinal_share_12m": "share of reported batches that were stomach medicines",
    "vitamin_share_12m": "share of reported batches that were vitamin or mineral supplements",
    "respiratory_share_12m": "share of reported batches that were cough and cold medicines",
    "cardiovascular_share_12m": "share of reported batches that were blood-pressure medicines",
    "antihistamine_share_12m": "share of reported batches that were antihistamines",
    "unclassified_share_12m": "share of reported batches whose kind could not be identified",
    "share_of_archive_reports_12m": "share of all reported batches in the archive over 12 months",
}

# The clause that travels with every explanation. Plan §12 and CLAUDE.md §6 both require it, and
# putting it in the text rather than in a page template means it cannot be lost by a redesign.
HISTORY_CLAUSE = (
    "This reflects how often batches have been reported, not the quality of the company's"
    " medicines."
)

# Words that must never appear in generated text about a named company. Checked by a test, because
# "be careful with the wording" is not a guarantee.
FORBIDDEN = (
    "fraud",
    "fraudulent",
    "fake",
    "counterfeit",
    "spurious",
    "unsafe",
    "dangerous",
    "poor quality",
    "bad quality",
    "substandard",
    "offender",
    "culprit",
    "guilty",
    "blacklist",
    "avoid",
    "risky company",
    "untrustworthy",
)


@dataclass(frozen=True)
class Contribution:
    """One feature's push on one prediction, in the units the model works in (log-odds)."""

    feature: str
    value: float
    push: float

    @property
    def direction(self) -> str:
        return "raises" if self.push > 0 else "lowers"

    def phrase(self) -> str:
        """Human text for this one contribution. Raises if the feature has no approved wording."""
        if self.feature not in PHRASES:
            raise KeyError(
                f"{self.feature!r} has no entry in PHRASES, so it cannot be described in public"
                " text. Add neutral wording for it first."
            )
        shown = (
            f"{self.value:.2f}".rstrip("0").rstrip(".") if np.isfinite(self.value) else "unknown"
        )
        return f"{PHRASES[self.feature]} ({shown}) {self.direction} the score"


class Explainer:
    """SHAP over the fitted LightGBM model.

    `shap.TreeExplainer` is exact for tree models - it enumerates the paths rather than sampling -
    so the contributions are not an approximation whose error has to be reasoned about.
    """

    def __init__(self, model: RiskModel) -> None:
        if model.model is None:
            raise RuntimeError("the model must be fitted before it can be explained")
        self.model = model
        self.explainer = shap.TreeExplainer(model.model)

    def values(self, frame: pd.DataFrame) -> np.ndarray:
        """One row of SHAP values per input row, in log-odds."""
        matrix = frame[list(FEATURE_COLUMNS)]
        computed = self.explainer.shap_values(matrix)
        # LightGBM binary classifiers have returned either an array or a two-element list across
        # shap versions; the positive class is what the score means either way.
        if isinstance(computed, list):
            computed = computed[1] if len(computed) == 2 else computed[0]
        return np.asarray(computed)

    @property
    def base_value(self) -> float:
        """The model's output before any feature moves it: the archive's background rate."""
        expected = self.explainer.expected_value
        if isinstance(expected, (list, np.ndarray)):
            expected = np.asarray(expected).ravel()
            return float(expected[1] if expected.size == 2 else expected[0])
        return float(expected)

    def global_importance(self, frame: pd.DataFrame) -> pd.Series:
        """Mean absolute contribution per feature: what the model relies on across many rows.

        Mean *absolute*, so a feature that pushes up for some companies and down for others is not
        cancelled out into looking unused.
        """
        return pd.Series(
            np.abs(self.values(frame)).mean(axis=0), index=list(FEATURE_COLUMNS)
        ).sort_values(ascending=False)

    def contributions(self, frame: pd.DataFrame, position: int, top: int = 3) -> list[Contribution]:
        """The `top` features that moved one row's prediction furthest, largest push first."""
        row_values = self.values(frame.iloc[[position]])[0]
        row = frame.iloc[position]
        ranked = sorted(
            (
                Contribution(feature=name, value=float(row[name]), push=float(push))
                for name, push in zip(FEATURE_COLUMNS, row_values, strict=True)
            ),
            key=lambda contribution: abs(contribution.push),
            reverse=True,
        )
        return ranked[:top]

    def additivity_error(self, frame: pd.DataFrame) -> float:
        """Largest gap between (base + contributions) and the model's own raw output.

        SHAP's guarantee is that those are equal. Checking it is how we know the sentences describe
        the prediction actually being shown, rather than a different one.
        """
        raw = self.model.model.predict(frame[list(FEATURE_COLUMNS)], raw_score=True)
        reconstructed = self.base_value + self.values(frame).sum(axis=1)
        return float(np.max(np.abs(np.asarray(raw) - reconstructed)))


def explanation_sentences(contributions: list[Contribution]) -> list[str]:
    """The public-facing text for one manufacturer, ending with the required clause."""
    if not contributions:
        return [HISTORY_CLAUSE]
    leading = contributions[0]
    lines = [f"Mainly {leading.phrase().replace(' the score', ' it')}."]
    for contribution in contributions[1:]:
        lines.append(f"Also {contribution.phrase()}.")
    lines.append(HISTORY_CLAUSE)
    return lines
