"""Shared test setup: silence Great Expectations' progress bars and pandas' warnings."""

import warnings

import pytest


@pytest.fixture(autouse=True)
def _quiet():
    # GE prints a metric progress bar per validation, which makes test output unreadable.
    warnings.filterwarnings("ignore")
    yield
