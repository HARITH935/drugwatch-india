"""Read the tables out of an HTML page with Python's built-in html.parser (no extra library).

Used by the CDSCO and NPPA adapters, whose listing pages are plain HTML tables. For each <table> it
keeps the tag's attributes, the header cells (<th>) and every row as a list of
(cell text, first link in the cell). Nested tables aren't supported: none of our sources use them.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

Cell = tuple[str, str | None]  # (text with whitespace collapsed, href of the cell's first link)


@dataclass
class Table:
    attrs: dict[str, str | None]  # the <table> tag's attributes, e.g. {"id": "example"}
    headers: list[str] = field(default_factory=list)  # text of every <th> cell, in order
    rows: list[list[Cell]] = field(default_factory=list)  # rows of <td> cells (header rows skipped)


def parse_tables(page: str) -> list[Table]:
    parser = _TableParser()
    parser.feed(page)
    parser.close()
    return parser.tables


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()  # convert_charrefs=True by default: "&amp;" arrives as "&"
        self.tables: list[Table] = []
        self._table: Table | None = None
        self._row: list[Cell] | None = None
        self._text: list[str] | None = None  # text pieces of the open cell
        self._href: str | None = None
        self._is_header = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = Table(dict(attrs))
            self.tables.append(self._table)
        elif self._table is None:
            return
        elif tag == "tr":
            self._end_row()  # HTML lets a page omit </tr>: a new row closes the previous one
            self._row = []
        elif tag in ("td", "th"):
            self._end_cell()  # HTML lets a page omit </td>: a new cell closes the previous one
            self._text, self._href, self._is_header = [], None, tag == "th"
        elif tag == "a" and self._text is not None and self._href is None:
            self._href = dict(attrs).get("href")

    def handle_data(self, data):
        if self._text is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._table is None:
            return
        if tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()
        elif tag == "table":
            self._end_row()  # a last row without </tr> still counts
            self._table = None

    def _end_row(self):
        self._end_cell()
        if self._row:  # a header row has only <th> cells, so it ends up empty: not kept
            self._table.rows.append(self._row)
        self._row = None

    def _end_cell(self):
        if self._text is None:
            return
        text = " ".join("".join(self._text).split())
        if self._is_header:
            self._table.headers.append(text)
        elif self._row is not None:
            self._row.append((text, self._href))
        self._text = None
