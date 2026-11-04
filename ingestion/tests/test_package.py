"""Smoke test: proves uv installed the package into .venv and pytest can import it."""

import drugwatch_ingestion


def test_version_comes_from_pyproject():
    assert drugwatch_ingestion.__version__ == "0.1.0"
