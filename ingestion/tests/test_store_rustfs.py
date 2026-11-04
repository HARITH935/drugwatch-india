"""Integration test: RawStore against the real local RustFS (docker compose).

Skipped unless RustFS credentials are in the environment (so, for now, in CI). Run it with:
    docker compose up -d --wait
    cd ingestion && uv run --env-file ../.env pytest -m integration
"""

import json
import os
import uuid

import pytest

from drugwatch_ingestion.store import RawStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "RUSTFS_ACCESS_KEY" not in os.environ,
        reason="needs local RustFS: uv run --env-file ../.env pytest",
    ),
]


@pytest.fixture
def temp_store():
    """A RawStore on a throwaway bucket, deleted afterwards: tests never write to the real raw/."""
    bucket = f"drugwatch-test-{uuid.uuid4().hex[:8]}"
    store = RawStore.from_env(bucket=bucket)
    store.s3.create_bucket(Bucket=bucket)
    yield store
    for obj in store.s3.list_objects_v2(Bucket=bucket).get("Contents", []):
        store.s3.delete_object(Bucket=bucket, Key=obj["Key"])
    store.s3.delete_bucket(Bucket=bucket)


def test_round_trip_and_skip_on_real_rustfs(temp_store):
    metadata = {"source": "test", "method": "auto", "alert_month": None}

    first = temp_store.put("test/item", b"hello rustfs", "txt", metadata)
    again = temp_store.put("test/item", b"hello rustfs", "txt", metadata)

    assert first.created
    assert not again.created
    assert temp_store.has_item("test/item")
    body = temp_store.s3.get_object(Bucket=temp_store.bucket, Key=first.key)["Body"].read()
    assert body == b"hello rustfs"
    sidecar_obj = temp_store.s3.get_object(Bucket=temp_store.bucket, Key=first.key + ".meta.json")
    assert json.loads(sidecar_obj["Body"].read())["sha256"] == first.sha256
