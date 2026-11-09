"""Integration test: family-C parser on the REAL archive in local RustFS (ADR 0003: not in git).

Pins today's results. Skipped in CI. Run with:
    cd extraction && uv run --env-file ../.env pytest -m integration
"""

import json
import os
import re

import pytest

from drugwatch_extraction.classify import classify_pdf
from drugwatch_extraction.family_c import parse_family_c
from drugwatch_ingestion.store import RawStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "RUSTFS_ACCESS_KEY" not in os.environ,
        reason="needs local RustFS: uv run --env-file ../.env pytest",
    ),
]


def _batch(text: str) -> str:
    return re.sub(r"\s+", "", text).upper().rstrip(".")


def test_family_c_parses_the_whole_archive():
    s3 = RawStore.from_env().s3
    files, rows, jun_2025 = 0, 0, None
    for prefix in ("cdsco-pdf/spurious/", "cdsco-pdf/combined/"):
        listing = s3.list_objects_v2(Bucket="raw", Prefix=prefix)["Contents"]
        for key in sorted(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf")):
            data = s3.get_object(Bucket="raw", Key=key)["Body"].read()
            if classify_pdf(data).family != "C":
                continue
            result = parse_family_c(data)
            assert result.serial_gaps == [] and result.unknown_headers == [], key
            assert not [s for s in result.skipped if s[1] == "row not recognised"], key
            files += 1
            rows += len(result.rows)
            if key.startswith("cdsco-pdf/spurious/2025-06/"):
                jun_2025 = {_batch(row.fields["batch_no"]) for row in result.rows}

    assert (files, rows) == (10, 24)

    # Jun 2025 is the one month the PDF and the portal's spurious list overlap: all 4 match.
    portal_key = next(
        obj["Key"]
        for obj in s3.list_objects_v2(Bucket="raw", Prefix="cdsco-portal/spurious/2025-06/")[
            "Contents"
        ]
        if obj["Key"].endswith(".json") and not obj["Key"].endswith(".meta.json")
    )
    portal = json.loads(s3.get_object(Bucket="raw", Key=portal_key)["Body"].read().decode("cp1252"))
    assert jun_2025 == {_batch(row["str_batch_no"]) for row in portal["aaData"]}
    assert len(jun_2025) == 4
