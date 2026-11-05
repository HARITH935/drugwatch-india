"""Manual drop: a hand-downloaded file goes into raw/ with who / when / where (ADR 0003 §2)."""

import json
import os
from datetime import UTC, datetime

import pytest

from drugwatch_ingestion import manual_drop
from drugwatch_ingestion.manual_drop import drop_file
from drugwatch_ingestion.store import RawStore

PAGE = "https://nppa.gov.in/en/compendiumofprice"
DOWNLOADED = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


@pytest.fixture
def csv_file(tmp_path):
    """A made-up CSV whose modified time is when it was 'downloaded'."""
    path = tmp_path / "ceiling-prices.csv"
    path.write_text("formulation,unit,ceiling_price\nTest Tablet 500 mg,1 tablet,1.23\n")
    os.utime(path, (DOWNLOADED.timestamp(), DOWNLOADED.timestamp()))  # (access, modified) times
    return path


def drop(store, path, **overrides):
    details = {
        "source": "nppa",
        "dataset": "compendium-2026",
        "period": "2026-11",
        "page_url": PAGE,
        "downloaded_by": "Test Person",
    }
    return drop_file(store, path, **(details | overrides))


def test_stores_the_file_with_who_when_and_where(raw_store, csv_file):
    stored = drop(raw_store, csv_file)

    assert stored.created
    assert stored.key.startswith("nppa/compendium-2026/2026-11/") and stored.key.endswith(".csv")
    assert raw_store.s3.objects[stored.key] == csv_file.read_bytes()
    sidecar = json.loads(raw_store.s3.objects[stored.key + ".meta.json"])
    assert sidecar["method"] == "manual"
    assert sidecar["manual"] == {
        "downloaded_by": "Test Person",
        "downloaded_at": "2026-11-05T10:00:00+00:00",
        "downloaded_at_from": "file modified time",
        "page_url": PAGE,
        "original_filename": "ceiling-prices.csv",
        "note": None,
    }


def test_an_explicit_download_time_wins(raw_store, csv_file):
    stored = drop(raw_store, csv_file, downloaded_at=datetime(2026, 11, 1, tzinfo=UTC))

    manual = json.loads(raw_store.s3.objects[stored.key + ".meta.json"])["manual"]
    assert manual["downloaded_at"] == "2026-11-01T00:00:00+00:00"
    assert manual["downloaded_at_from"] == "--downloaded-at"


def test_dropping_the_same_file_twice_stores_it_once(raw_store, csv_file):
    drop(raw_store, csv_file)
    writes = len(raw_store.s3.puts)

    again = drop(raw_store, csv_file)

    assert not again.created
    assert len(raw_store.s3.puts) == writes


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source": "NPPA Prices"}, "source must be"),
        ({"dataset": "compendium_2026"}, "dataset must be"),
        ({"period": "Nov-2026"}, "period must look like"),
        ({"period": "2026-13"}, "period must look like"),
        ({"page_url": "nppa.gov.in/en/compendiumofprice"}, "http"),
        ({"page_url": "file:///Users/someone/Downloads"}, "http"),
        ({"downloaded_by": "  "}, "who downloaded"),
    ],
)
def test_rejects_a_bad_description(raw_store, csv_file, overrides, message):
    with pytest.raises(ValueError, match=message):
        drop(raw_store, csv_file, **overrides)

    assert raw_store.s3.objects == {}


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("empty.csv", b"", "between 1 byte and 100 MB"),
        ("prices.pdf", b"<!DOCTYPE html><html>Error</html>", "isn't a PDF"),
        ("prices", b"a,b\n1,2\n", "needs an extension"),
    ],
)
def test_rejects_a_bad_file(raw_store, tmp_path, name, content, message):
    path = tmp_path / name
    path.write_bytes(content)

    with pytest.raises(ValueError, match=message):
        drop(raw_store, path)


def test_rejects_a_missing_file(raw_store, tmp_path):
    with pytest.raises(ValueError, match="no such file"):
        drop(raw_store, tmp_path / "not-there.csv")


def test_command_line(raw_store, csv_file, monkeypatch, capsys):
    monkeypatch.setattr(RawStore, "from_env", lambda: raw_store)  # use the fake store, not RustFS
    argv = [
        str(csv_file),
        "--source",
        "nppa",
        "--dataset",
        "compendium-2026",
        "--period",
        "2026-11",
    ]
    argv += ["--page-url", PAGE, "--downloaded-by", "Test Person", "--downloaded-at", "2026-11-05"]

    manual_drop.main(argv)

    assert capsys.readouterr().out.startswith("stored -> raw/nppa/compendium-2026/2026-11/")


def test_command_line_reports_problems_without_a_traceback(raw_store, csv_file, monkeypatch):
    monkeypatch.setattr(RawStore, "from_env", lambda: raw_store)
    argv = [str(csv_file), "--source", "nppa", "--dataset", "compendium-2026", "--period", "Nov"]
    argv += ["--page-url", PAGE, "--downloaded-by", "Test Person"]

    with pytest.raises(SystemExit) as exit_info:  # argparse's parser.error() exits with status 2
        manual_drop.main(argv)

    assert exit_info.value.code == 2
