"""Integration test: family-B parser on the REAL archive in local RustFS (ADR 0003: not in git).

Pins today's results so a later change can't quietly make the parser worse. Skipped in CI. Run with:
    cd extraction && uv run --env-file ../.env pytest -m integration
"""

import json
import os
import re

import pytest

from drugwatch_extraction.classify import classify_pdf
from drugwatch_extraction.family_b import parse_family_b
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


def _first_key(s3, prefix: str, suffix: str) -> str:
    return next(
        obj["Key"]
        for obj in s3.list_objects_v2(Bucket="raw", Prefix=prefix)["Contents"]
        if obj["Key"].endswith(suffix) and not obj["Key"].endswith(".meta.json")
    )


def test_family_b_parses_the_whole_archive_and_agrees_with_the_portal():
    s3 = RawStore.from_env().s3
    files = rows = found = pdf_total = covered = portal_total = 0
    for dataset, lab in (("central-nsq", "cdsco"), ("state-nsq", "state")):
        listing = s3.list_objects_v2(Bucket="raw", Prefix=f"cdsco-pdf/{dataset}/")["Contents"]
        for key in sorted(obj["Key"] for obj in listing if obj["Key"].endswith(".pdf")):
            data = s3.get_object(Bucket="raw", Key=key)["Body"].read()
            if classify_pdf(data).family != "B":
                continue
            result = parse_family_b(data)
            assert result.serial_gaps == [] and result.first_serial == 1, key
            assert not [s for s in result.skipped if s[1] == "row not recognised"], key
            files += 1
            rows += len(result.rows)

            month = key.split("/")[2]
            portal_key = _first_key(s3, f"cdsco-portal/nsq/{month}/", ".json")
            body = s3.get_object(Bucket="raw", Key=portal_key)["Body"].read()
            portal = json.loads(body.decode("cp1252"))  # the portal's bytes aren't UTF-8 (§1b)
            pdf_batches = {_batch(row.fields["batch_no"]) for row in result.rows}
            portal_batches = {
                _batch(row["str_batch_no"])
                for row in portal["aaData"]
                if row["str_reporting_source"].strip().lower().startswith(lab)
            }
            found += len(pdf_batches & portal_batches)
            pdf_total += len(pdf_batches)
            covered += len(portal_batches & pdf_batches)
            portal_total += len(portal_batches)

    assert (files, rows) == (19, 1179)
    # 2026-11-08: 93.8% / 95.1%. The rest are rows only one source lists, and the portal dropping
    # leading zeros or dashes ("04010026" -> "4010026", "CHI – 40139" -> "CHI ? 40139").
    assert found / pdf_total >= 0.93
    assert covered / portal_total >= 0.95
