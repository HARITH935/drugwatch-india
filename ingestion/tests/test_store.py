"""RawStore: content-addressed keys, never-overwrite, sidecar as the "done" marker (unit tests)."""

import hashlib
import json

import pytest

META = {"source": "cdsco-portal", "method": "auto", "alert_month": "2026-09"}


def test_stores_bytes_under_their_hash_with_a_sidecar(raw_store):
    result = raw_store.put("cdsco-portal/nsq/2026-09", b'{"rows": []}', "json", META)

    sha = hashlib.sha256(b'{"rows": []}').hexdigest()
    assert result.created
    assert result.key == f"cdsco-portal/nsq/2026-09/{sha}.json"
    assert raw_store.s3.objects[result.key] == b'{"rows": []}'
    sidecar = json.loads(raw_store.s3.objects[result.key + ".meta.json"])
    assert sidecar["source"] == "cdsco-portal"
    assert sidecar["alert_month"] == "2026-09"
    assert sidecar["sha256"] == sha
    assert sidecar["size_bytes"] == len(b'{"rows": []}')
    assert "stored_at" in sidecar
    assert raw_store.s3.puts == [result.key, result.key + ".meta.json"]  # sidecar written last


def test_same_bytes_twice_writes_nothing(raw_store):
    raw_store.put("nppa/ceiling-prices", b"same", "pdf", META)
    writes_before = len(raw_store.s3.puts)

    again = raw_store.put("nppa/ceiling-prices", b"same", "pdf", META)

    assert not again.created
    assert len(raw_store.s3.puts) == writes_before


def test_changed_file_is_kept_next_to_the_old_one(raw_store):
    old = raw_store.put("jan-aushadhi/products", b"version 1", "json", META)
    new = raw_store.put("jan-aushadhi/products", b"version 2", "json", META)

    assert new.created and new.key != old.key
    assert raw_store.s3.objects[old.key] == b"version 1"  # never overwritten
    assert raw_store.s3.objects[new.key] == b"version 2"


def test_has_item_needs_a_sidecar(raw_store):
    assert not raw_store.has_item("cdsco-pdf/central/2025-06")

    # Simulate a crash after the file was written but before its sidecar:
    raw_store.s3.put_object(Bucket="raw", Key="cdsco-pdf/central/2025-06/abc.pdf", Body=b"%PDF")
    assert not raw_store.has_item("cdsco-pdf/central/2025-06")

    raw_store.put("cdsco-pdf/central/2025-06", b"%PDF", "pdf", META)  # the next run repairs it
    assert raw_store.has_item("cdsco-pdf/central/2025-06")


def test_has_item_does_not_match_a_longer_prefix(raw_store):
    raw_store.put("cdsco-portal/nsq/2026-09", b"x", "json", META)

    assert not raw_store.has_item("cdsco-portal/nsq/2026-0")


def test_computed_fields_cannot_be_overridden(raw_store):
    result = raw_store.put("test/item", b"x", "txt", {**META, "sha256": "fake"})

    sidecar = json.loads(raw_store.s3.objects[result.key + ".meta.json"])
    assert sidecar["sha256"] == result.sha256


@pytest.mark.parametrize(
    ("prefix", "ext", "metadata", "message"),
    [
        ("", "pdf", META, "bad item prefix"),
        ("a//b", "pdf", META, "bad item prefix"),
        ("a/../b", "pdf", META, "bad item prefix"),
        ("/a", "pdf", META, "bad item prefix"),
        ("a", ".pdf", META, "bad file extension"),
        ("a", "pdf", {"method": "auto"}, "missing \\['source'\\]"),
        ("a", "pdf", {"source": "x", "method": "scraped"}, "must be auto or manual"),
    ],
)
def test_rejects_bad_input(raw_store, prefix, ext, metadata, message):
    with pytest.raises(ValueError, match=message):
        raw_store.put(prefix, b"x", ext, metadata)
