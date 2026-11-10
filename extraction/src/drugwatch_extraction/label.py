"""Label the eval-set rows by hand (Phase 2 step 7): check every pre-filled value against the PDF.

For each manifest row not labelled yet, the tool saves a picture of the PDF page with the row
outlined in red and opens it in Preview (in the background), then asks field by field:

    batch_no        [TB-1201]:
      Enter   the value shown is exactly what the PDF prints
      text    what the PDF prints instead (on one line: line breaks and spacing don't count)
      /b      the cell is blank
      /u      you can't read it (e.g. two texts printed on top of each other)
      /q      stop; every finished row is already saved

A finished row is appended to ../data/eval-set/labels.jsonl at once, so you can stop and resume
any time; `--redo N` labels row N again (the newer label replaces the older). The labelling guide
is docs/eval-set.md.

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.label
"""

import argparse
import io
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pdfplumber

from drugwatch_extraction.bronze import bronze_key, read_bronze
from drugwatch_extraction.confidence import REQUIRED, SHARED
from drugwatch_extraction.eval_set import (
    LABELS,
    MANIFEST,
    append_label,
    load_labels,
    read_manifest,
    row_id,
)
from drugwatch_ingestion.store import RawStore

COMMANDS = {"/b": "", "/u": None}  # answer -> stored value: "" = blank cell, None = unreadable


class Quit(Exception):
    """The labeller typed /q."""


def label_fields(record: dict[str, Any], ask: Callable[[str], str] = input) -> dict[str, Any]:
    """Ask for every field the row's layout has; returns the label's fields and note."""
    fields: dict[str, str | None] = {}
    for field in REQUIRED.get(record["family"], SHARED):
        shown = record.get(field) or ""
        while True:
            answer = ask(f"  {field:15} [{shown.replace(chr(10), ' ⏎ ')}]: ").strip()
            if answer == "/q":
                raise Quit
            if answer.startswith("/") and answer not in COMMANDS:
                print("    Enter = as shown, /b = blank cell, /u = unreadable, /q = stop")
                continue
            break
        if answer == "":
            fields[field] = shown  # as shown, line breaks included
        else:
            fields[field] = COMMANDS.get(answer, answer)
    note = ask("  note (Enter to save the row): ").strip()
    if note == "/q":
        raise Quit
    return {"fields": fields, "note": note}


def row_box(page: Any, serial: str) -> tuple | None:
    """The bounding box of the table row whose first cell is this S.No, if it is on the page."""
    for table in page.find_tables():
        for row, texts in zip(table.rows, table.extract(), strict=True):
            if (texts[0] or "").strip().rstrip(".") == serial:
                return row.bbox
    return None


def save_picture(pdf: bytes, page_no: int, serial: str | None, path: Path) -> Path:
    """A PNG of the page, with the row outlined in red (serial None: a continuation page)."""
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        page = document.pages[page_no - 1]
        image = page.to_image(resolution=120)
        if serial is not None and (box := row_box(page, serial)) is not None:
            image.draw_rect(box, fill=(255, 0, 0, 25), stroke=(220, 0, 0), stroke_width=3)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    return path


def show(path: Path) -> None:
    if sys.platform == "darwin":  # -g: open in the background, so the terminal keeps the focus
        subprocess.run(["/usr/bin/open", "-g", str(path)], check=False)  # noqa: S603
    else:
        print(f"  picture: {path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Label the eval-set rows by hand.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--redo", type=int, metavar="N", help="label row N of the manifest again")
    args = parser.parse_args(argv)

    manifest = read_manifest(args.manifest)
    done = load_labels(args.labels)
    if args.redo:  # the new label replaces the old one (load_labels keeps the latest)
        if not 1 <= args.redo <= len(manifest):
            sys.exit(f"--redo: choose a row from 1 to {len(manifest)}")
        todo = [manifest[args.redo - 1]]
    else:
        todo = [item for item in manifest if row_id(item) not in done]
    print(
        f"{_progress(args.labels, manifest)}."
        + (f" Labelling row {args.redo} again." if args.redo else "")
    )
    print("Enter = as shown, /b = blank, /u = unreadable, /q = stop. Guide: docs/eval-set.md\n")

    s3 = RawStore.from_env().s3
    records: dict[tuple, dict] = {}  # row id -> bronze record, loaded one PDF at a time
    pictures = args.labels.parent / "pages"  # git-ignored, next to the labels
    pdfs: dict[str, bytes] = {}
    first = args.redo or len(manifest) - len(todo) + 1
    for position, item in enumerate(todo, start=first):
        key = item["source_key"]
        if key not in pdfs:
            pdfs[key] = s3.get_object(Bucket="raw", Key=key)["Body"].read()
            for record in read_bronze(s3, bronze_key(key)).to_pylist():
                records[row_id(record)] = record
        # A row the parser lost has no bronze record: label it from the picture, nothing pre-filled.
        record = records.get(row_id(item), {"family": item["family"]})
        sha, page, serial = row_id(item)
        where = f"{item['source_dataset']} {item['alert_month']}, file {item['file_id']}"
        pages = record.get("pages") or [page]
        more = f" (continues on page {', '.join(map(str, pages[1:]))})" if len(pages) > 1 else ""
        print(f"Row {position} of {len(manifest)}: {where}, page {page}, S.No {serial}{more}")
        for shown_page in pages:  # the row's first page outlined, then any continuation pages
            name = f"{sha[:16]}-p{shown_page}-{serial}.png"
            outline = serial if shown_page == page else None
            show(save_picture(pdfs[key], shown_page, outline, pictures / name))
        try:
            answers = label_fields(record)
        except (Quit, EOFError, KeyboardInterrupt):
            print(f"\nStopped. {_progress(args.labels, manifest)}; every finished row is saved.")
            return
        append_label(
            args.labels,
            {
                "source_sha256": sha,
                "page": page,
                "serial_no": serial,
                "family": item["family"],
                **answers,
                "method": "checked",  # pre-filled values checked against the picture (Harith)
                "prefilled_by": record.get("extractor_version"),
                "labelled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
    print(f"\nDone. {_progress(args.labels, manifest)}.")


def _progress(labels: Path, manifest: list[dict]) -> str:
    done = load_labels(labels)
    return f"{sum(row_id(item) in done for item in manifest)} of {len(manifest)} rows labelled"


if __name__ == "__main__":
    main()
