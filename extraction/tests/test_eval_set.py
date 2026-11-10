"""eval_set.py: a reproducible sample, splits by whole PDF, a fixed manifest, resumable labels."""

import os
from collections import defaultdict

import pytest

from drugwatch_extraction.eval_set import (
    MANIFEST,
    append_label,
    assign_splits,
    bronze_files,
    load_labels,
    manifest_rows,
    read_manifest,
    row_id,
    sample_rows,
    write_manifest,
)
from drugwatch_ingestion.store import RawStore


def pdf(name: str, rows: int, family: str = "B") -> list[dict]:
    """Made-up records of one PDF (only the fields sampling uses)."""
    sha = name * 64
    return [
        {
            "source_key": f"cdsco-pdf/x/{name}.pdf",
            "source_sha256": sha,
            "page": 1 + i // 10,
            "serial_no": f"{i + 1}.",
            "row_index": i + 1,
            "family": family,
        }  # fmt: skip
        for i in range(rows)
    ]


def test_up_to_n_rows_per_pdf_and_small_pdfs_whole():
    sampled = sample_rows([pdf("a", 50), pdf("b", 3)], per_file=12)

    by_file = defaultdict(list)
    for row in sampled:
        by_file[row["source_key"]].append(row["row_index"])
    assert len(by_file["cdsco-pdf/x/a.pdf"]) == 12
    assert by_file["cdsco-pdf/x/b.pdf"] == [1, 2, 3]  # all of it
    assert by_file["cdsco-pdf/x/a.pdf"] == sorted(by_file["cdsco-pdf/x/a.pdf"])  # document order


def test_the_same_seed_draws_the_same_rows_whatever_the_input_order():
    files = [pdf("a", 50), pdf("b", 40)]

    first = sample_rows(files, seed=7)

    assert sample_rows(list(reversed(files)), seed=7) == first
    assert sample_rows(files, seed=8) != first


def test_duplicate_row_ids_are_refused():
    twin = pdf("a", 2)
    twin[1]["serial_no"] = "1"  # same page, same S.No as row 1

    with pytest.raises(ValueError, match="not unique"):
        sample_rows([twin])


def test_splits_are_by_whole_pdf_and_follow_the_shares():
    files = [pdf(name, 12) for name in "abcdefghij"]  # one family, 10 equal PDFs
    sampled = sample_rows(files)

    split_of = assign_splits(sampled)

    assert sorted(split_of.values()).count("train") == 6
    assert sorted(split_of.values()).count("validation") == 2
    assert sorted(split_of.values()).count("test") == 2
    rows = manifest_rows(sampled, split_of)
    assert {r["source_sha256"]: r["split"] for r in rows} == split_of  # one split per PDF


def test_a_family_with_two_pdfs_reaches_train_and_test_and_one_pdf_goes_to_train():
    sampled = sample_rows([pdf("a", 12, "D"), pdf("b", 12, "D"), pdf("c", 5, "F")])

    split_of = assign_splits(sampled)

    assert sorted([split_of["a" * 64], split_of["b" * 64]]) == ["test", "train"]
    assert split_of["c" * 64] == "train"


def test_the_manifest_round_trips_and_is_never_overwritten(tmp_path):
    sampled = sample_rows([pdf("a", 3)])
    rows = manifest_rows(sampled, assign_splits(sampled))
    path = tmp_path / "manifest.csv"

    write_manifest(path, rows)

    back = read_manifest(path)
    assert [row_id(r) for r in back] == [("a" * 64, 1, "1"), ("a" * 64, 1, "2"), ("a" * 64, 1, "3")]
    assert "Test Tablet" not in path.read_text()  # IDs only: no row text in the manifest
    with pytest.raises(FileExistsError, match="fixed"):
        write_manifest(path, rows)


def test_labels_append_and_the_latest_label_of_a_row_wins(tmp_path):
    path = tmp_path / "labels.jsonl"
    first = {"source_sha256": "a" * 64, "page": 1, "serial_no": "1", "fields": {"batch_no": "X"}}

    append_label(path, first)
    append_label(path, first | {"fields": {"batch_no": "Y"}})  # labelled again
    append_label(path, first | {"serial_no": "2"})

    labels = load_labels(path)
    assert len(labels) == 2
    assert labels[("a" * 64, 1, "1")]["fields"] == {"batch_no": "Y"}


def test_no_labels_yet_is_an_empty_set(tmp_path):
    assert load_labels(tmp_path / "missing.jsonl") == {}


@pytest.mark.integration
@pytest.mark.skipif("RUSTFS_ACCESS_KEY" not in os.environ, reason="needs local RustFS")
def test_the_committed_manifest_is_what_the_code_draws_from_bronze():
    sampled = sample_rows(bronze_files(RawStore.from_env().s3))
    drawn = manifest_rows(sampled, assign_splits(sampled))

    committed = read_manifest(MANIFEST)

    assert [(row_id(r), r["split"]) for r in committed] == [(row_id(r), r["split"]) for r in drawn]
    assert len(committed) == 309
