"""Label the eval-set rows by hand (Phase 2 step 7): check every pre-filled value against the PDF.

For each manifest row not labelled yet, the tool saves a picture of the PDF page with the row
outlined in red and opens it in Preview (in front), then asks field by field:

    batch_no        [TB-1201]:
      Enter   the value shown is exactly what the PDF prints
      text    what the PDF prints instead (on one line: line breaks and spacing don't count)
      /b      the cell is blank
      /u      you can't read it (e.g. two texts printed on top of each other)
      /q      stop; every finished row is already saved

Two safety nets keep every answer a real check: keys pressed BEFORE a question appears are thrown
away (so extra Enters can't answer the next row), and a row answered faster than MIN_SECONDS is
asked again.

A finished row is appended to ../data/eval-set/labels.jsonl at once, so you can stop and resume
any time; `--redo N` labels row N again (the newer label replaces the older). The labelling guide
is docs/eval-set.md.

`--review` decides only the values where the parser and the second reader disagree
(second_reader.py): it shows that row's picture and asks 1 (parser), 2 (second reader) or the
value typed.

Run (from extraction/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.label            # or --review
"""

import argparse
import io
import json
import subprocess
import sys
import termios
import time
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
# Checking a whole row against the picture takes longer than this. In the first sessions, 64 of 72
# rows were saved within 7 s of the previous one (Enter pressed repeatedly): none of them checked.
MIN_SECONDS = 8


class Quit(Exception):
    """The labeller typed /q."""


def ask_now(prompt: str) -> str:
    """input(), but first throw away anything typed before the question appeared."""
    if sys.stdin.isatty():
        termios.tcflush(sys.stdin, termios.TCIFLUSH)  # discard keys still waiting to be read
    return input(prompt)


def label_fields(
    record: dict[str, Any],
    ask: Callable[[str], str] = ask_now,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Ask for every field the row's layout has; ask the whole row again if it went too fast."""
    while True:
        started = clock()
        answers = _ask_row(record, ask)
        if clock() - started >= MIN_SECONDS:
            return answers
        print(
            f"\n  That took under {MIN_SECONDS} seconds: too fast to have compared it with the"
            " picture.\n  Look at the red box, then answer this row again.\n"
        )


def _ask_row(record: dict[str, Any], ask: Callable[[str], str]) -> dict[str, Any]:
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


def review_fields(
    differ: dict[str, dict],
    ask: Callable[[str], str] = ask_now,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """--review: for each value the two readings disagree on, the person picks 1 (parser) or 2
    (second reader) or types the right value. Asked again if it went too fast."""
    while True:
        started = clock()
        decided = _review_once(differ, ask)
        if clock() - started >= MIN_SECONDS:
            return decided
        print(
            f"\n  That took under {MIN_SECONDS} seconds. Look at the picture, then decide again.\n"
        )


def _review_once(differ: dict[str, dict], ask: Callable[[str], str]) -> dict[str, Any]:
    fields: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    for field, pair in differ.items():
        print(f"  {field}:")
        print(f"    1  parser:        {_shown(pair['parser'])}")
        print(f"    2  second reader: {_shown(pair['second_reader'])}")
        while True:
            answer = ask("    Which matches the picture? 1 / 2 / type it / /b / /u / /q: ").strip()
            if answer == "/q":
                raise Quit
            if answer in ("1", "2"):
                source = "parser" if answer == "1" else "second_reader"
                fields[field], sources[field] = pair[source], source
            elif answer in COMMANDS or (answer and not answer.startswith("/")):
                fields[field], sources[field] = COMMANDS.get(answer, answer), "typed"
            else:
                print("    1 = the parser's value, 2 = the second reader's, or type what you see")
                continue
            break
    return {"fields": fields, "decided": sources}


def _shown(value: str | None) -> str:
    return "(can't read it)" if value is None else "[" + value.replace("\n", " ⏎ ") + "]"


def review(args: argparse.Namespace, manifest: list[dict]) -> None:
    """Decide the rows where the parser and the second reader disagree (second_reader.py)."""
    queue = [
        json.loads(line)
        for line in (args.labels.parent / "disagreements.jsonl").read_text().splitlines()
        if line.strip()
    ]
    done = load_labels(args.labels)
    todo = [q for q in queue if row_id(manifest[q["row"] - 1]) not in done]
    print(f"{len(todo)} row(s) to decide. 1 = parser, 2 = second reader, or type the value.\n")
    for q in todo:
        item = manifest[q["row"] - 1]
        sha, page, serial = row_id(item)
        where = f"{item['source_dataset']} {item['alert_month']}, file {item['file_id']}"
        print(f"Row {q['row']} of {len(manifest)}: {where}, page {page}, S.No {serial}")
        show(args.labels.parent / "crops" / f"{q['row']:03d}.png")  # just this row
        try:
            decided = review_fields(q["differ"])
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
                "fields": q["agreed"] | decided["fields"],
                "decided": decided["decided"],  # which values a person decided, and how
                "note": "",
                "method": "parser and second reader (Claude, from the picture); "
                "disagreements decided by Harith",
                "labelled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        print()
    print(f"Done. {_progress(args.labels, manifest)}.")


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
    if sys.platform == "darwin":  # Preview comes to the front; click the terminal to answer
        subprocess.run(["/usr/bin/open", str(path)], check=False)  # noqa: S603
    else:
        print(f"  picture: {path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Label the eval-set rows by hand.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--redo", type=int, metavar="N", help="label row N of the manifest again")
    parser.add_argument("--review", action="store_true", help="decide parser vs second reader")
    args = parser.parse_args(argv)

    manifest = read_manifest(args.manifest)
    if args.review:
        review(args, manifest)
        return
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
