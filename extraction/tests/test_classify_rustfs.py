"""Integration test: classify the REAL CDSCO PDFs in the local raw/ archive (ADR 0003: not in git).

Skipped unless RustFS credentials are in the environment (so skipped in CI). Run with:
    cd extraction && uv run --env-file ../.env pytest -m integration
"""

import os
from collections import Counter

import pytest

from drugwatch_extraction.classify import classify_pdf
from drugwatch_ingestion.store import RawStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "RUSTFS_ACCESS_KEY" not in os.environ,
        reason="needs local RustFS: uv run --env-file ../.env pytest",
    ),
]

# docs/data-sources.md §7.1 and docs/extraction-report.md: update both if CDSCO adds files.
EXPECTED_FAMILIES = {"A": 11, "B": 19, "C": 10, "D": 2, "E": 1, "F": 1}


def test_every_real_pdf_is_readable_with_a_known_family():
    s3 = RawStore.from_env().s3
    keys = [
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket="raw", Prefix="cdsco-pdf/")
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".pdf")
    ]

    results = [classify_pdf(s3.get_object(Bucket="raw", Key=key)["Body"].read()) for key in keys]

    assert Counter(result.family for result in results) == EXPECTED_FAMILIES
    assert all(result.readable for result in results)
