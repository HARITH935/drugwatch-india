"""Put the AWS SDK bundle (686 MB) for Spark's S3 connector into the local Maven repository,
downloaded in parallel pieces that resume after a dropped connection (ADR 0008).

Spark resolves `spark.jars.packages` through a chain that starts with ~/.m2/repository, then
Maven Central. Spark's own download is a single stream that restarts from zero when the connection
drops; on a slow, unstable link it may never finish a 686 MB file. This puts the big jar where
Spark looks first, after checking it against the SHA-256 Maven Central publishes. Spark still
downloads the small files (hadoop-aws and two helpers) itself.

Run once per machine, before the first S3 job (from spark/):
    uv run python -m drugwatch_spark.prefetch
"""

import hashlib
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from drugwatch_spark.session import AWS_SDK_VERSION

CENTRAL = "https://repo1.maven.org/maven2"
BUNDLE = f"software/amazon/awssdk/bundle/{AWS_SDK_VERSION}/bundle-{AWS_SDK_VERSION}"
M2 = Path.home() / ".m2" / "repository"
PIECES = 4  # parallel connections: this link is slow per connection, not overall
TRIES = 20  # per piece; each try continues where the last one stopped
USER_AGENT = "drugwatch-india/0.1 (+https://github.com/HARITH935/drugwatch-india)"

OpenRange = Callable[[str, int, int], Iterator[bytes]]  # (url, first byte, last byte) -> chunks


def pieces(size: int, count: int = PIECES) -> list[tuple[int, int]]:
    """Split bytes 0..size-1 into `count` contiguous (first, last) ranges."""
    step = -(-size // count)  # ceiling division
    return [(start, min(start + step, size) - 1) for start in range(0, size, step)]


def fetch_piece(url: str, first: int, last: int, part: Path, open_range: OpenRange) -> None:
    """Download bytes first..last into `part`, continuing from what `part` already holds."""
    for attempt in range(TRIES):
        have = part.stat().st_size if part.exists() else 0
        if first + have > last:
            return  # this piece is complete
        try:
            with part.open("ab") as out:
                for chunk in open_range(url, first + have, last):
                    out.write(chunk)
        except OSError as error:  # dropped connection, timeout: keep what arrived, try again
            print(f"  piece {first}-{last}: {error}; retrying ({attempt + 1}/{TRIES})", flush=True)
            time.sleep(min(2**attempt, 30))
    if first + (part.stat().st_size if part.exists() else 0) <= last:
        raise OSError(f"piece {first}-{last} still incomplete after {TRIES} tries")


def fetch(url: str, dest: Path, size: int, sha256: str, open_range: OpenRange) -> Path:
    """Download `url` to `dest` in resumable pieces, then check its SHA-256 before keeping it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ranges = pieces(size)
    parts = [dest.with_name(f"{dest.name}.part{i}") for i in range(len(ranges))]
    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        jobs = [pool.submit(fetch_piece, url, f, last, p, open_range)
                for (f, last), p in zip(ranges, parts, strict=True)]  # fmt: skip
        for job in jobs:
            job.result()  # re-raises a piece's error here
    digest = hashlib.sha256()
    with dest.with_name(dest.name + ".tmp").open("wb") as joined:
        for part in parts:
            data = part.read_bytes()
            digest.update(data)
            joined.write(data)
    if digest.hexdigest() != sha256:
        dest.with_name(dest.name + ".tmp").unlink()
        for part in parts:
            part.unlink()
        raise ValueError(f"{url}: SHA-256 doesn't match Maven Central's; download discarded")
    dest.with_name(dest.name + ".tmp").replace(dest)  # appears only once complete and verified
    for part in parts:
        part.unlink()
    return dest


def http_range(url: str, first: int, last: int) -> Iterator[bytes]:
    headers = {"Range": f"bytes={first}-{last}", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 206:  # the server must honour the range, or pieces would overlap
            raise OSError(f"expected a partial response (206), got {response.status}")
        while chunk := response.read(1 << 20):
            yield chunk


def _get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode()


def _size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return int(response.headers["Content-Length"])


def main() -> None:
    jar = M2 / f"{BUNDLE}.jar"
    if jar.exists():
        print(f"already there: {jar}")
        return
    sha256 = _get_text(f"{CENTRAL}/{BUNDLE}.jar.sha256").split()[0]
    size = _size(f"{CENTRAL}/{BUNDLE}.jar")
    print(f"downloading {size / 1e6:.0f} MB in {PIECES} resumable pieces -> {jar}", flush=True)
    started = time.monotonic()
    fetch(f"{CENTRAL}/{BUNDLE}.jar", jar, size, sha256, http_range)
    (M2 / f"{BUNDLE}.pom").write_text(_get_text(f"{CENTRAL}/{BUNDLE}.pom"))  # Spark reads its deps
    print(f"done in {(time.monotonic() - started) / 60:.1f} min; SHA-256 verified")


if __name__ == "__main__":
    sys.exit(main())
