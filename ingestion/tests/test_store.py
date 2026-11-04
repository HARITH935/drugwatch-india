"""RawStore: content-addressed keys, never-overwrite, sidecar as the "done" marker (unit tests)."""

import hashlib
import json

import pytest
from botocore.exceptions import ClientError

from drugwatch_ingestion.store import RawStore


class FakeS3:
    """In-memory stand-in for a boto3 S3 client: only the three calls RawStore uses."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}  # key -> body
        self.puts: list[str] = []  # keys written, in order

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body
        self.puts.append(Key)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {}

    def list_objects_v2(self, Bucket, Prefix):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}


META = {"source": "cdsco-portal", "method": "auto", "alert_month": "2026-09"}


@pytest.fixture
def store() -> RawStore:
    return RawStore(FakeS3())


def test_stores_bytes_under_their_hash_with_a_sidecar(store):
    result = store.put("cdsco-portal/nsq/2026-09", b'{"rows": []}', "json", META)

    sha = hashlib.sha256(b'{"rows": []}').hexdigest()
    assert result.created
    assert result.key == f"cdsco-portal/nsq/2026-09/{sha}.json"
    assert store.s3.objects[result.key] == b'{"rows": []}'
    sidecar = json.loads(store.s3.objects[result.key + ".meta.json"])
    assert sidecar["source"] == "cdsco-portal"
    assert sidecar["alert_month"] == "2026-09"
    assert sidecar["sha256"] == sha
    assert sidecar["size_bytes"] == len(b'{"rows": []}')
    assert "stored_at" in sidecar
    assert store.s3.puts == [result.key, result.key + ".meta.json"]  # sidecar written last


def test_same_bytes_twice_writes_nothing(store):
    store.put("nppa/ceiling-prices", b"same", "pdf", META)
    writes_before = len(store.s3.puts)

    again = store.put("nppa/ceiling-prices", b"same", "pdf", META)

    assert not again.created
    assert len(store.s3.puts) == writes_before


def test_changed_file_is_kept_next_to_the_old_one(store):
    old = store.put("jan-aushadhi/products", b"version 1", "json", META)
    new = store.put("jan-aushadhi/products", b"version 2", "json", META)

    assert new.created and new.key != old.key
    assert store.s3.objects[old.key] == b"version 1"  # never overwritten
    assert store.s3.objects[new.key] == b"version 2"


def test_has_item_needs_a_sidecar(store):
    assert not store.has_item("cdsco-pdf/central/2025-06")

    # Simulate a crash after the file was written but before its sidecar:
    store.s3.put_object(Bucket="raw", Key="cdsco-pdf/central/2025-06/abc.pdf", Body=b"%PDF")
    assert not store.has_item("cdsco-pdf/central/2025-06")

    store.put("cdsco-pdf/central/2025-06", b"%PDF", "pdf", META)  # the next run repairs it
    assert store.has_item("cdsco-pdf/central/2025-06")


def test_has_item_does_not_match_a_longer_prefix(store):
    store.put("cdsco-portal/nsq/2026-09", b"x", "json", META)

    assert not store.has_item("cdsco-portal/nsq/2026-0")


def test_computed_fields_cannot_be_overridden(store):
    result = store.put("test/item", b"x", "txt", {**META, "sha256": "fake"})

    sidecar = json.loads(store.s3.objects[result.key + ".meta.json"])
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
def test_rejects_bad_input(store, prefix, ext, metadata, message):
    with pytest.raises(ValueError, match=message):
        store.put(prefix, b"x", ext, metadata)
