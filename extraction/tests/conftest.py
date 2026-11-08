"""Shared test helpers. No real CDSCO file is committed (ADR 0003): tests build their own PDFs."""

import pytest


def make_table_pdf(rows: list[list[str]], *, blank_pages: int = 0) -> bytes:
    """A tiny real PDF: one page with a ruled table (lines around every cell, text inside), plus
    optional empty pages. A PDF is text-based underneath: numbered objects, then a cross-reference
    table ("xref") of their byte offsets, which is how readers like pdfplumber find them."""
    cell_w, cell_h, left, top = 70, 20, 20, 800
    drawing = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            x, y = left + c * cell_w, top - (r + 1) * cell_h
            drawing.append(f"{x} {y} {cell_w} {cell_h} re S")  # rectangle, stroked = cell borders
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            drawing.append(f"BT /F1 6 Tf {x + 2} {y + 7} Td ({safe}) Tj ET")  # text inside the cell
    content = "\n".join(drawing)

    page_count = 1 + blank_pages
    page_ids = [4 + 2 * i for i in range(page_count)]  # each page: a page object + a content stream
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {page_count} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i in range(page_count):
        stream = content if i == 0 else ""
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

    pdf, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return pdf


@pytest.fixture
def table_pdf():
    return make_table_pdf
