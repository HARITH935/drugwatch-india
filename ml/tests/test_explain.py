"""SHAP explanations: the arithmetic, and the wording rules CLAUDE.md §6 imposes.

These sentences are about named Indian companies on a public site, so the wording tests are not
style checks - they are the mechanism that keeps a generated sentence from becoming an accusation.
"""

import numpy as np
import pandas as pd
import pytest

from drugwatch_ml.explain import (
    FORBIDDEN,
    HISTORY_CLAUSE,
    PHRASES,
    Contribution,
    Explainer,
    explanation_sentences,
)
from drugwatch_ml.features import FEATURE_COLUMNS, LABEL_COLUMN
from drugwatch_ml.model import RiskModel


def fake(rows: int = 400, seed: int = 0) -> pd.DataFrame:
    generator = np.random.default_rng(seed)
    data = {column: generator.random(rows) for column in FEATURE_COLUMNS}
    data["reports_24m"] = generator.integers(0, 30, rows).astype("float64")
    frame = pd.DataFrame(data)
    frame["manufacturer_id"] = [f"m{i % 40}" for i in range(rows)]
    frame["as_of_month"] = "2025-01"
    frame[LABEL_COLUMN] = (frame["reports_24m"] > 15).astype("int8")
    return frame


@pytest.fixture(scope="module")
def fitted():
    return RiskModel().fit(fake(seed=1))


# ------------------------------------------------------------------ the wording rules


def test_every_feature_has_approved_wording():
    """A feature with no phrase cannot be explained in public. That is the design: new wording is
    written by a person before a new feature can appear in a sentence about a company."""
    missing = [column for column in FEATURE_COLUMNS if column not in PHRASES]
    assert missing == [], f"these features have no public wording: {missing}"


def test_no_phrase_contains_a_forbidden_word():
    """CLAUDE.md §6: never call a manufacturer fraudulent, never imply the medicine is unsafe."""
    for feature, phrase in PHRASES.items():
        lowered = phrase.lower()
        for word in FORBIDDEN:
            assert word not in lowered, f"{feature}: {phrase!r} contains {word!r}"


def test_no_phrase_claims_anything_about_quality():
    """The distinction the whole project turns on: these are *reported* findings from a non-random
    sample, so a phrase may describe reporting and must not describe the medicine."""
    for feature, phrase in PHRASES.items():
        assert "quality" not in phrase.lower(), f"{feature}: {phrase!r}"
        assert "failed" not in phrase.lower() or "test failures" in phrase.lower(), (
            f"{feature}: {phrase!r} reads as a verdict rather than a test result"
        )


def test_the_phrases_describe_reports_not_the_company():
    """Each phrase must be about batches, tests, products or laboratories - the things CDSCO
    actually published - rather than about the manufacturer as an entity."""
    subjects = (
        "batches",
        "reported",
        "products",
        "laboratories",
        "test failures",
        "medicine-class",
        "kinds of medicine",
        "months since",
        "change in",
        "share of",
        "states whose",
    )
    for feature, phrase in PHRASES.items():
        assert any(subject in phrase for subject in subjects), f"{feature}: {phrase!r}"


def test_every_explanation_carries_the_reporting_history_clause():
    """Required by plan §12 and CLAUDE.md §6. It lives in the text, not in a page template, so a
    redesign of the website cannot drop it."""
    contributions = [Contribution("reports_24m", 19.0, 0.9)]
    lines = explanation_sentences(contributions)
    assert lines[-1] == HISTORY_CLAUSE
    assert "not the quality" in HISTORY_CLAUSE


def test_an_empty_explanation_is_still_honest():
    """No contributions worth naming must not produce a bare score with no context."""
    assert explanation_sentences([]) == [HISTORY_CLAUSE]


def test_generated_sentences_contain_no_forbidden_word():
    contributions = [
        Contribution(feature, 1.0, 0.5 if index % 2 else -0.5)
        for index, feature in enumerate(FEATURE_COLUMNS)
    ]
    text = " ".join(explanation_sentences(contributions)).lower()
    for word in FORBIDDEN:
        assert word not in text, f"generated text contains {word!r}"


def test_a_feature_without_wording_refuses_to_be_described():
    """Rather than falling back to the column name, which would put `assay_share_12m` in front of
    a reader, or worse, a future column whose name is not neutral."""
    with pytest.raises(KeyError, match="no entry in PHRASES"):
        Contribution("some_new_feature", 1.0, 0.5).phrase()


def test_the_direction_words_are_neutral():
    """ "raises" and "lowers", not "worsens" and "improves" - the score is not a grade."""
    assert Contribution("reports_24m", 5.0, 0.4).direction == "raises"
    assert Contribution("reports_24m", 0.0, -0.4).direction == "lowers"


# ------------------------------------------------------------------ the arithmetic


def test_contributions_add_up_to_the_prediction(fitted):
    """SHAP's guarantee, checked rather than trusted: if base + contributions did not equal the
    model's own output, the sentences would describe a different prediction from the one shown."""
    explainer = Explainer(fitted)
    assert explainer.additivity_error(fake(seed=2)) < 1e-6


def test_global_importance_uses_absolute_contributions(fitted):
    """Mean absolute, so a feature that pushes up for some companies and down for others is not
    cancelled into looking unused."""
    importance = Explainer(fitted).global_importance(fake(seed=2))
    assert set(importance.index) == set(FEATURE_COLUMNS)
    assert (importance >= 0).all()
    assert importance.is_monotonic_decreasing


def test_contributions_are_ordered_by_absolute_push(fitted):
    contributions = Explainer(fitted).contributions(fake(seed=2), position=0, top=5)
    pushes = [abs(contribution.push) for contribution in contributions]
    assert pushes == sorted(pushes, reverse=True)
    assert len(contributions) == 5


def test_explaining_an_unfitted_model_is_refused():
    with pytest.raises(RuntimeError, match="must be fitted"):
        Explainer(RiskModel())


def test_the_base_value_is_a_single_number(fitted):
    """shap has returned both an array and a scalar for LightGBM across versions; the sentences
    need one number, and silently taking the wrong element would shift every explanation."""
    base = Explainer(fitted).base_value
    assert isinstance(base, float)
    assert np.isfinite(base)
