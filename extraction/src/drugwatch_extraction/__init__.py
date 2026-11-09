"""DrugWatch India extraction: turns CDSCO alert PDFs from raw/ into structured rows (Phase 2)."""

from importlib.metadata import version

# Read from the installed package metadata (pyproject.toml), so it's defined in one place.
__version__ = version("drugwatch-extraction")
