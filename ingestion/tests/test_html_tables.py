"""The shared HTML table reader used by the CDSCO and NPPA adapters."""

from drugwatch_ingestion.sources.html_tables import parse_tables


def test_reads_headers_cells_and_the_first_link_of_each_cell():
    page = """
    <a href="/menu">Menu link outside any table</a>
    <table id="docs" class="x">
      <tr><th>Sr.No.</th><th>Document Name</th><th>Download</th></tr>
      <tr><td>1</td><td>Prices &amp; lists
          2026</td><td><a href="/a.pdf">1MB</a> <a href="/b.pdf">other</a></td></tr>
    </table>"""

    [table] = parse_tables(page)

    assert table.attrs == {"id": "docs", "class": "x"}
    assert table.headers == ["Sr.No.", "Document Name", "Download"]
    assert table.rows == [[("1", None), ("Prices & lists 2026", None), ("1MB other", "/a.pdf")]]


def test_copes_with_cells_whose_closing_tags_are_left_out():
    page = "<table><tr><td>1<td>two<td><a href='x.pdf'>3</a></tr><tr><td>4</table>"

    [table] = parse_tables(page)

    assert table.rows == [[("1", None), ("two", None), ("3", "x.pdf")], [("4", None)]]


def test_keeps_tables_apart():
    page = "<table><tr><td>a</td></tr></table><p>text</p><table><tr><td>b</td></tr></table>"

    assert [table.rows for table in parse_tables(page)] == [[[("a", None)]], [[("b", None)]]]
