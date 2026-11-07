"""Inventory check: finds every way raw/ could be incomplete or changed."""

import json

import pytest

from drugwatch_ingestion import inventory
from drugwatch_ingestion.inventory import check_bucket
from drugwatch_ingestion.store import RawStore

AUTO = {"source": "cdsco-portal", "method": "auto", "dataset": "nsq"}
MANUAL = {"source": "nppa", "method": "manual", "dataset": "compendium-2026"}


@pytest.fixture
def filled(raw_store):
    """A raw store holding two automatic files and one manual drop."""
    raw_store.put("cdsco-portal/nsq/2026-08", b'{"aaData": [1]}', "json", AUTO)
    raw_store.put("cdsco-portal/nsq/2026-09", b'{"aaData": [1, 2]}', "json", AUTO)
    manual = raw_store.put("nppa/compendium-2026/2026-11", b"a,b\n1,2\n", "csv", MANUAL)
    raw_store.manual_key = manual.key  # remembered so tests can tamper with it
    return raw_store


def test_a_complete_bucket_has_no_problems_and_is_counted(filled):
    report = check_bucket(filled.s3)

    assert report.problems == []
    assert report.files == 3
    nsq = report.groups[("cdsco-portal", "nsq")]
    assert (nsq.files, nsq.manual, nsq.size_bytes) == (2, 0, 15 + 18)
    assert report.groups[("nppa", "compendium-2026")].manual == 1


def test_finds_a_file_without_its_sidecar(filled):
    filled.s3.objects["cdsco-portal/nsq/2026-10/" + "a" * 64 + ".json"] = b"{}"

    [problem] = check_bucket(filled.s3).problems

    assert "no sidecar" in problem


def test_finds_a_sidecar_whose_file_is_missing(filled):
    del filled.s3.objects[filled.manual_key]

    [problem] = check_bucket(filled.s3).problems

    assert "is missing" in problem


def test_finds_changed_bytes(filled):
    filled.s3.objects[filled.manual_key] = b"a,b\n1,999\n"  # someone edited raw/

    problems = check_bucket(filled.s3).problems

    assert any("no longer match their SHA-256" in p for p in problems)


def test_skipping_the_hash_check_is_faster_but_blind_to_changed_bytes(filled):
    filled.s3.objects[filled.manual_key] = b"a,b\n1,999\n"

    assert check_bucket(filled.s3, verify_hashes=False).problems == []


def test_finds_a_broken_or_incomplete_sidecar(filled):
    sidecar = filled.manual_key + ".meta.json"
    filled.s3.objects[sidecar] = b"{not json"
    assert any("not valid JSON" in p for p in check_bucket(filled.s3).problems)

    filled.s3.objects[sidecar] = json.dumps({"source": "nppa"}).encode()
    assert any("missing fields" in p for p in check_bucket(filled.s3).problems)


def test_finds_a_sidecar_that_points_at_another_file(filled):
    sidecar = filled.manual_key + ".meta.json"
    meta = json.loads(filled.s3.objects[sidecar])
    filled.s3.objects[sidecar] = json.dumps(meta | {"key": "nppa/somewhere/else.csv"}).encode()

    problems = check_bucket(filled.s3).problems

    assert any("belongs to nppa/somewhere/else.csv" in p for p in problems)


def test_follows_listing_pages(filled):
    filled.s3.page_size = 2  # 6 keys (3 files + 3 sidecars) now take 3 listing pages

    report = check_bucket(filled.s3)

    assert report.files == 3 and report.problems == []


def test_command_line_exit_status(filled, monkeypatch, capsys):
    monkeypatch.setattr(RawStore, "from_env", lambda: filled)

    inventory.main([])
    assert "no problems found" in capsys.readouterr().out

    del filled.s3.objects[filled.manual_key]
    with pytest.raises(SystemExit) as exit_info:
        inventory.main([])
    assert exit_info.value.code == 1  # a scheduler sees the run as failed
    assert "1 PROBLEM(S)" in capsys.readouterr().out
