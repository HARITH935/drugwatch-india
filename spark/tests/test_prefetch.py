"""prefetch.py: pieces, resuming after a dropped connection, and refusing a wrong checksum."""

import hashlib

import pytest

from drugwatch_spark import prefetch
from drugwatch_spark.prefetch import fetch, pieces

DATA = bytes(range(256)) * 40  # 10,240 made-up bytes


def server(data: bytes, drop_after: int | None = None):
    """A fake range server. drop_after: each piece's first request breaks after this many bytes."""
    seen: set[int] = set()

    def open_range(url, first, last):
        body = data[first : last + 1]
        piece = first // 3000  # roughly which piece asked (pieces here are ~2,560 bytes)
        if drop_after is not None and piece not in seen:
            seen.add(piece)
            yield body[:drop_after]
            raise ConnectionResetError("connection dropped")
        yield body

    return open_range


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(prefetch.time, "sleep", lambda seconds: None)


def test_pieces_cover_every_byte_exactly_once():
    ranges = pieces(10_240, 4)

    assert ranges == [(0, 2559), (2560, 5119), (5120, 7679), (7680, 10239)]
    assert pieces(10, 4) == [(0, 2), (3, 5), (6, 8), (9, 9)]  # uneven sizes still covered


def test_a_download_is_joined_and_verified(tmp_path):
    dest = tmp_path / "bundle.jar"

    fetch("u", dest, len(DATA), hashlib.sha256(DATA).hexdigest(), server(DATA))

    assert dest.read_bytes() == DATA
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bundle.jar"]  # pieces cleaned up


def test_a_dropped_connection_continues_where_it_stopped(tmp_path, capsys):
    dest = tmp_path / "bundle.jar"

    fetch("u", dest, len(DATA), hashlib.sha256(DATA).hexdigest(), server(DATA, drop_after=100))

    assert dest.read_bytes() == DATA  # nothing lost, nothing written twice
    assert "connection dropped" in capsys.readouterr().out


def test_a_wrong_checksum_keeps_nothing(tmp_path):
    dest = tmp_path / "bundle.jar"

    with pytest.raises(ValueError, match="SHA-256"):
        fetch("u", dest, len(DATA), "0" * 64, server(DATA))

    assert list(tmp_path.iterdir()) == []  # no half-trusted file left behind
