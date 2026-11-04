"""DrugWatch India ingestion: downloads source files politely into RustFS raw/ (Phase 1)."""

from importlib.metadata import version

# Read the version from installed package metadata (pyproject.toml), so it's defined in one place.
__version__ = version("drugwatch-ingestion")
