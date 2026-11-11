"""AI-assisted labels for the eval set (Phase 2 step 7; Harith's decision, 2026-11-11).

Harith had no time to check all 309 rows by hand, so each label comes from TWO INDEPENDENT READINGS:
1. the parser: pdfplumber reads the PDF's hidden text layer (the bronze records);
2. a second reader (Claude) reads a PICTURE of the row, drawn from the PDF by pypdfium2, without
   seeing the parser's values.
Where the two agree (spaces and line breaks ignored), that is the label. Where they disagree, Harith
decides, looking at the picture (`label --review`). The report says so: "AI-assisted labels; every
disagreement decided by a person." A value both readings get wrong in the same way would be missed;
that is unlikely, because the two methods share nothing but the PDF.

    --render    one picture per manifest row: the table's header, the row, and any part of it that
                continues on the next page -> ../data/eval-set/crops/NNN.png (NNN = row number)
    --compare   readings vs parser: agreeing rows -> labels.jsonl, the rest -> disagreements.jsonl

The second reader's file, ../data/eval-set/second-reader.jsonl, has one JSON object per row:
    {"row": 37, "fields": {"batch_no": "TB-1201", ...}}    ("" = blank cell, null = can't read it)

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.second_reader --render
    uv run --env-file ../.env python -m drugwatch_extraction.second_reader --compare
"""

import argparse
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

import pdfplumber
from PIL import Image

from drugwatch_extraction import family_a, family_b, family_c, family_d, family_e, family_f
from drugwatch_extraction.bronze import bronze_key, read_bronze
from drugwatch_extraction.confidence import REQUIRED, SHARED
from drugwatch_extraction.eval_set import LABELS, append_label, load_labels, read_manifest, row_id
from drugwatch_extraction.table_parser import Vocabulary, header_fields, is_header
from drugwatch_ingestion.store import RawStore

CROPS = LABELS.parent / "crops"
READINGS = LABELS.parent / "second-reader.jsonl"
DISAGREEMENTS = LABELS.parent / "disagreements.jsonl"
RESOLUTION = 150  # dots per inch: small print stays readable
VOCABULARIES: dict[str, Vocabulary] = {
    "A": family_a.VOCABULARY, "B": family_b.VOCABULARY, "C": family_c.VOCABULARY,
    "D": family_d.VOCABULARY, "E": family_e.VOCABULARY, "F": family_f.VOCABULARY,
}  # fmt: skip

Strip = tuple[int, tuple[float, float, float, float]]  # (page number, bounding box)


def _serial(text: str | None) -> str:
    return (text or "").strip().rstrip(".")


def _union(boxes: list[tuple]) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))  # fmt: skip


def row_strips(document: Any, page_no: int, serial: str, pages: list[int], vocabulary: Vocabulary,
               ) -> list[Strip]:  # fmt: skip
    """Where to cut the picture: the latest header before the row, the row itself (with the
    unnumbered rows under it, e.g. split cells), and its continuation on later pages."""
    header: Strip | None = None
    for number in range(1, page_no + 1):
        for table in document.pages[number - 1].find_tables():
            rows = list(zip(table.rows, table.extract(), strict=True))
            for i, (row, texts) in enumerate(rows):
                if is_header(header_fields(texts, vocabulary)):
                    header = (number, row.bbox)
                elif number == page_no and _serial(texts[0]) == serial:
                    boxes = [row.bbox]
                    for below, below_texts in rows[i + 1 :]:
                        if (below_texts[0] or "").strip():  # the next numbered or section row
                            break
                        boxes.append(below.bbox)
                    strips = [header] if header else []
                    strips.append((number, _union(boxes)))
                    return strips + _continuations(document, pages[1:], vocabulary)
    raise LookupError(f"S.No {serial} not found on page {page_no}")


def _continuations(document: Any, pages: list[int], vocabulary: Vocabulary) -> list[Strip]:
    """The top rows of each later page that have no S.No (the rest of a row cut by a page break)."""
    strips = []
    for number in pages:
        tables = document.pages[number - 1].find_tables()
        boxes = []
        for row, texts in zip(tables[0].rows, tables[0].extract(), strict=True) if tables else []:
            if is_header(header_fields(texts, vocabulary)):
                continue  # a repeated header at the top of the page
            if (texts[0] or "").strip():
                break
            boxes.append(row.bbox)
        if boxes:
            strips.append((number, _union(boxes)))
    return strips


def render_row(pdf: bytes, page_no: int, serial: str, pages: list[int], family: str) -> Image.Image:
    """One picture: the strips stacked top to bottom, with a grey gap between them."""
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        parts = []
        for number, (x0, top, x1, bottom) in row_strips(
            document, page_no, serial, pages, VOCABULARIES[family]
        ):
            page = document.pages[number - 1]
            box = (
                max(x0 - 2, 0),
                max(top - 2, 0),
                min(x1 + 2, page.width),
                min(bottom + 2, page.height),
            )
            parts.append(page.crop(box).to_image(resolution=RESOLUTION).original.convert("RGB"))
    gap = 8
    picture = Image.new(
        "RGB", (max(p.width for p in parts), sum(p.height + gap for p in parts)), "#999"
    )
    y = 0
    for part in parts:
        picture.paste(part, (0, y))
        y += part.height + gap
    return picture


def _same(a: str | None, b: str | None) -> bool:
    """Equal once spaces and line breaks are removed (they don't count, docs/eval-set.md §4)."""
    if a is None or b is None:
        return False  # "can't read it" never agrees: a person decides
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def compare(item: dict, reading: dict, record: dict | None) -> tuple[dict, dict]:
    """(agreed fields with the parser's value, disagreeing fields with both values)."""
    expected = set(REQUIRED.get(item["family"], SHARED))
    if set(reading["fields"]) != expected:
        raise ValueError(
            f"row {reading['row']}: read {sorted(reading['fields'])}, need {sorted(expected)}"
        )
    agreed, differ = {}, {}
    for field, read in reading["fields"].items():
        parsed = (record or {}).get(field) or ""  # no record: the parser lost the row
        if _same(read, parsed):
            agreed[field] = parsed
        else:
            differ[field] = {"parser": parsed, "second_reader": read}
    return agreed, differ


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AI-assisted eval-set labels (second reader).")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--render", action="store_true", help="make one picture per manifest row")
    action.add_argument("--compare", action="store_true", help="compare readings with the parser")
    args = parser.parse_args(argv)

    s3 = RawStore.from_env().s3
    manifest = read_manifest()
    records: dict[tuple, dict] = {}
    for key in sorted({item["source_key"] for item in manifest}):
        records |= {row_id(r): r for r in read_bronze(s3, bronze_key(key)).to_pylist()}

    if args.render:
        CROPS.mkdir(parents=True, exist_ok=True)
        pdfs: dict[str, bytes] = {}
        for number, item in enumerate(manifest, start=1):
            key = item["source_key"]
            if key not in pdfs:
                pdfs[key] = s3.get_object(Bucket="raw", Key=key)["Body"].read()
            sha, page, serial = row_id(item)
            pages = (records.get(row_id(item)) or {}).get("pages") or [
                page
            ]  # pages only, no values
            render_row(pdfs[key], page, serial, pages, item["family"]).save(
                CROPS / f"{number:03d}.png"
            )
        print(f"{len(manifest)} pictures -> {CROPS}")
        return

    readings = {}
    for line in READINGS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            reading = json.loads(line)
            readings[reading["row"]] = reading  # a row read again replaces the earlier reading
    done = load_labels(LABELS)
    agreed_rows, queue, field_counts = 0, [], {"agree": 0, "differ": 0}
    for number, reading in sorted(readings.items()):
        item = manifest[number - 1]
        agreed, differ = compare(item, reading, records.get(row_id(item)))
        field_counts["agree"] += len(agreed)
        field_counts["differ"] += len(differ)
        if row_id(item) in done:
            continue
        if differ:
            queue.append({"row": number, "agreed": agreed, "differ": differ})
            continue
        sha, page, serial = row_id(item)
        append_label(LABELS, {
            "source_sha256": sha, "page": page, "serial_no": serial, "family": item["family"],
            "fields": agreed, "note": "",
            "method": "parser and second reader (Claude, from the picture) agree",
            "labelled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        })  # fmt: skip
        agreed_rows += 1
    DISAGREEMENTS.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in queue))
    print(f"{len(readings)} rows read; fields: {field_counts['agree']} agree, "
          f"{field_counts['differ']} differ")  # fmt: skip
    print(f"{agreed_rows} new rows labelled (all fields agree); {len(queue)} rows wait for Harith")
    labelled = sum(row_id(item) in load_labels(LABELS) for item in manifest)
    print(f"labelled so far: {labelled} of {len(manifest)}")


if __name__ == "__main__":
    main()
