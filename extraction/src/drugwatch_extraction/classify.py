"""Classify each CDSCO alert PDF before it is parsed (Phase 2 step 1).

Two questions per PDF:
1. Is every page real text? A scanned page (a picture of paper) would need OCR, which isn't in our
   stack, so it must be reported, not silently parsed as empty.
2. Which LAYOUT FAMILY is it? Each family gets its own parser (docs/data-sources.md §7.1):
     A  vaccine lists 2017-2023          B  NSQ lists 2024-2025 (central + state)
     C  spurious / combined 2024-2025    D  combined lists 2018
     E  bulk vaccine file 2017-2023      F  spurious list Apr 2024 (sales outlets, maker's response)
   The family is decided from the table's header words, not from the file's date or name, so a new
   layout comes out as "unknown" instead of being parsed with the wrong rules.

Header words are looked for inside table CELLS. In the page's running text a header that wraps onto
two lines is read across all columns ("Product/Drug Batch No. ... Name Date"), so phrases break.

Run (from extraction/, with RustFS up):
    uv run --env-file ../.env python -m drugwatch_extraction.classify
"""

import argparse
import io
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass

import pdfplumber

from drugwatch_ingestion.store import META_SUFFIX, RawStore

TEXT_MIN_CHARS = 50  # a page with at least this many characters is real text
SCANNED_MIN_IMAGE_COVER = 0.5  # ...otherwise, images over half the page means a scan

# (family, what it is, groups of phrases). A family matches when EVERY group has at least one of its
# phrases in the header cells. Phrases are compared with spaces removed and in lower case, because
# CDSCO's headers break words across lines ("Manufactu ring Date").
# Order matters: the first match wins, so specific rules come first (D before C, E before A).
FAMILY_RULES = (
    ("E", "bulk vaccine file 2017-2023", (("detailofsamplesdeclared",), ("regulatoryaction",))),
    ("F", "spurious list Apr 2024", (("salesoutletsinvolved",), ("responseoforiginalmanufactur",))),
    ("A", "vaccine list", (("vaccinename",), ("nsqresult",))),
    ("D", "combined list 2018", (("batchno./dateofmanu",), ("reasonforfailure",))),
    ("C", "spurious / combined list", (("reasonforfailure",), ("drawnby",))),
    # 2024 files say "Name of Drugs/medical device/cosmetics", 2025 files "Product/Drug Name".
    ("B", "NSQ list", (("nsqresult",), ("product/drugname", "nameofdrugs"))),
)
FAMILY_NAMES = {family: name for family, name, _ in FAMILY_RULES} | {"unknown": "unknown layout"}


@dataclass(frozen=True)
class PageStats:
    chars: int  # characters pdfplumber found on the page
    image_cover: float  # share of the page covered by images, 0 to 1


@dataclass(frozen=True)
class PdfClass:
    pages: int
    page_kinds: dict[str, int]  # {"text": n, "scanned": n, "blank": n}
    family: str  # A-E, or "unknown"

    @property
    def readable(self) -> bool:
        """True if no page is a scan (blank pages are fine: there's nothing on them to miss)."""
        return self.page_kinds["scanned"] == 0


def page_kind(stats: PageStats) -> str:
    if stats.chars >= TEXT_MIN_CHARS:
        return "text"
    if stats.image_cover > SCANNED_MIN_IMAGE_COVER:
        return "scanned"
    return "blank"


def layout_family(header_cells: list[str]) -> str:
    """The first family whose phrase groups all match the header cells, or "unknown"."""
    # Cells are squashed one by one and joined with "|": two cells' words never form a phrase.
    squashed = "|".join(re.sub(r"\s+", "", cell.lower()) for cell in header_cells)
    for family, _, groups in FAMILY_RULES:
        if all(any(phrase in squashed for phrase in group) for group in groups):
            return family
    return "unknown"


def classify_pdf(data: bytes) -> PdfClass:
    """Measure every page of a PDF and name its layout family."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        kinds = Counter(page_kind(_measure(page)) for page in pdf.pages)
        # The first 3 rows of every table on the first 2 pages: the header (and any section or
        # title row above it) is always in there, even when a title takes up the top of page 1.
        header_cells = [
            cell
            for page in pdf.pages[:2]
            for table in page.extract_tables()
            for row in table[:3]
            for cell in row
            if cell
        ]
        return PdfClass(
            pages=len(pdf.pages),
            page_kinds={kind: kinds[kind] for kind in ("text", "scanned", "blank")},
            family=layout_family(header_cells),
        )


def _measure(page) -> PageStats:
    page_area = float(page.width * page.height) or 1.0
    image_area = sum(
        float((image["x1"] - image["x0"]) * (image["bottom"] - image["top"]))
        for image in page.images
    )
    return PageStats(chars=len(page.chars), image_cover=min(image_area / page_area, 1.0))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Classify the CDSCO alert PDFs in raw/.")
    parser.add_argument("--prefix", default="cdsco-pdf/", help="which part of raw/ to classify")
    args = parser.parse_args(argv)

    s3 = RawStore.from_env().s3
    keys = [
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket="raw", Prefix=args.prefix)
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".pdf")
    ]
    families: Counter[str] = Counter()
    problems = []
    for key in sorted(keys):
        meta = json.loads(s3.get_object(Bucket="raw", Key=key + META_SUFFIX)["Body"].read())
        result = classify_pdf(s3.get_object(Bucket="raw", Key=key)["Body"].read())
        families[result.family] += 1
        kinds = result.page_kinds
        month = meta.get("alert_month") or "-"
        print(
            f"{result.family:<8} {meta.get('dataset', '-'):<12} {month:<8} {result.pages:>3}p "
            f"text={kinds['text']:<3} scanned={kinds['scanned']:<2} blank={kinds['blank']:<2} {key}"
        )
        if result.family == "unknown":
            problems.append(f"{key}: layout family unknown (a new layout? see FAMILY_RULES)")
        if not result.readable:
            problems.append(f"{key}: {kinds['scanned']} scanned page(s) need OCR")
    print("\nby family:")
    for family, count in sorted(families.items()):
        print(f"  {family:<8} {FAMILY_NAMES[family]:<30} {count:>3}")
    print(f"  {'total':<39} {sum(families.values()):>3}")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)  # a scheduler treats the run as failed
    print("every PDF is readable text with a known layout family")


if __name__ == "__main__":
    main()
