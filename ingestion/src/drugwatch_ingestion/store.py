"""RawStore: saves downloaded bytes into the RustFS `raw` bucket and never overwrites anything.

Layout, for one "item" (one logical thing we download, e.g. CDSCO portal NSQ rows for Sep 2026):

    <item prefix>/<sha256>.<ext>             the bytes exactly as downloaded
    <item prefix>/<sha256>.<ext>.meta.json   metadata "sidecar": source, URL, alert month, hash ...

- Each file is named after the SHA-256 hash of its content. The same bytes always get the same
  name, so storing them again is skipped. If a source changes a file, the new version lands next to
  the old one, never over it (raw/ is never modified: CLAUDE.md §5).
- The sidecar is written last and is the "done" marker: an item counts as stored only once a
  sidecar exists, so a crash between the two writes is repaired by the next run.
- Sidecars are plain JSON, so later phases (Spark, bronze) can read provenance from the bucket.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

META_SUFFIX = ".meta.json"
# method is "auto" (fetched by the downloader) or "manual" (browser download, ADR 0003)
REQUIRED_METADATA = frozenset({"source", "method"})


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    created: bool  # False = these exact bytes were already stored, so nothing was written


class RawStore:
    def __init__(self, s3_client: Any, bucket: str = "raw"):
        self.s3 = s3_client  # a boto3 S3 client (unit tests pass an in-memory fake)
        self.bucket = bucket

    @classmethod
    def from_env(cls, bucket: str = "raw") -> "RawStore":
        """Connect to RustFS using the same variables as docker-compose.yml (.env)."""
        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("RUSTFS_ENDPOINT", "http://localhost:9000"),
            aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
            aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
            region_name="us-east-1",  # request signing (SigV4) needs a region; RustFS takes any
            config=Config(s3={"addressing_style": "path"}),  # host/bucket/key URLs (ADR 0002)
        )
        return cls(client, bucket)

    def has_item(self, prefix: str) -> bool:
        """True if at least one complete version (file + sidecar) is stored under this item."""
        _check_prefix(prefix)
        # One listing call returns up to 1,000 keys: plenty, since an item has only a few versions.
        response = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=f"{prefix}/")
        return any(obj["Key"].endswith(META_SUFFIX) for obj in response.get("Contents", []))

    def put(self, prefix: str, content: bytes, ext: str, metadata: dict[str, Any]) -> StoredObject:
        """Store `content` under `prefix` unless these exact bytes are already there."""
        _check_prefix(prefix)
        if not ext.isalnum():
            raise ValueError(f"bad file extension {ext!r}: use e.g. 'pdf' or 'json'")
        missing = REQUIRED_METADATA - metadata.keys()
        if missing:
            raise ValueError(f"metadata is missing {sorted(missing)}")
        if metadata["method"] not in ("auto", "manual"):
            raise ValueError(f"metadata method must be auto or manual, not {metadata['method']!r}")

        sha256 = hashlib.sha256(content).hexdigest()
        key = f"{prefix}/{sha256}.{ext}"
        if self._exists(key + META_SUFFIX):
            return StoredObject(key=key, sha256=sha256, created=False)

        sidecar = {
            **metadata,
            # Added last, so callers can't accidentally override the computed facts:
            "key": key,
            "sha256": sha256,
            "size_bytes": len(content),
            "stored_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=content)
        self.s3.put_object(  # written second: its presence means "this file is complete"
            Bucket=self.bucket,
            Key=key + META_SUFFIX,
            Body=json.dumps(sidecar, indent=2, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        return StoredObject(key=key, sha256=sha256, created=True)

    def _exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)  # HEAD: "is it there?", no body
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise  # anything else (bad credentials, RustFS down) is a real error: fail loudly
        return True


def _check_prefix(prefix: str) -> None:
    """Item prefixes look like 'cdsco-portal/nsq/2026-09': no empty, '.' or '..' parts."""
    if not prefix or any(part in ("", ".", "..") for part in prefix.split("/")):
        raise ValueError(f"bad item prefix {prefix!r}")
