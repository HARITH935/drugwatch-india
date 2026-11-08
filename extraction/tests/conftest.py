"""Shared test helpers. No real CDSCO file is committed (ADR 0003): tests build their own PDFs."""

import pytest

CELL_W, CELL_H, LEFT, TOP = 70, 20, 10, 800

Cell = str | tuple[str, float]  # text, or (text, width) for a narrower or wider cell


def make_table_pdf(*tables: list[list[Cell]], blank_pages: int = 0) -> bytes:
    """A tiny real PDF with one ruled table per page (lines around every cell, text inside), plus
    optional empty pages. A cell is a string (70 points wide) or (text, width), so tests can draw a
    column split into narrow pieces, like CDSCO's Apr 2024 page 4.

    A PDF is text-based underneath: numbered objects, then a cross-reference table ("xref") of their
    byte offsets, which is how readers like pdfplumber find them.
    """
    streams = [_draw_table(rows) for rows in tables] + [""] * blank_pages
    page_ids = [4 + 2 * i for i in range(len(streams))]  # each page: page object + content stream
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [" + " ".join(f"{p} 0 R" for p in page_ids) + "]"
        f" /Count {len(streams)} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for page_id, stream in zip(page_ids, streams, strict=True):
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

    pdf, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return pdf + trailer.encode()


def _draw_table(rows: list[list[Cell]]) -> str:
    drawing = []
    for r, row in enumerate(rows):
        x, y = LEFT, TOP - (r + 1) * CELL_H
        for cell in row:
            text, width = (cell, CELL_W) if isinstance(cell, str) else cell
            drawing.append(f"{x} {y} {width} {CELL_H} re S")  # rectangle, stroked = cell borders
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            drawing.append(f"BT /F1 6 Tf {x + 2} {y + 7} Td ({safe}) Tj ET")  # text in the cell
            x += width
    return "\n".join(drawing)


@pytest.fixture
def table_pdf():
    return make_table_pdf
