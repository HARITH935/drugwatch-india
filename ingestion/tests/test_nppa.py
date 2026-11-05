"""NPPA adapter, against a fake NPPA site on localhost (made-up documents, no real price data)."""

import json

import pytest

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.sources.nppa import (
    ORDERS_PATH,
    REFERENCE_PATHS,
    Nppa,
    order_documents,
    reference_documents,
)

PAGE_URL = "https://nppa.gov.in/en/dpco2013"
FAKE_PDF = b"%PDF-1.4 made-up test file"
FAKE_DATA_PAGE = b"<html><table><tr><td>Test Tablet</td><td>1.23</td></tr></table></html>"


def reference_page(*rows: str) -> str:
    """A page shaped like NPPA's: site menu link + a 'Document Name' table with the given rows."""
    return (
        "<a href='https://nppa.gov.in/HIS/manual.pdf'>Click Here</a>"
        "<table class='table'><tr><th>Sr.No.</th><th>Document Name</th><th>Download</th></tr>"
        f"{''.join(rows)}</table>"
    )


def orders_page(*rows: str) -> str:
    return (
        "<table id='example2'><tr><th>Sr. No.</th><th>Date</th>"
        "<th>Title</th><th>Attachment</th></tr>"
        f"{''.join(rows)}</table>"
    )


def test_reference_rows_become_pdf_and_html_documents():
    page = reference_page(
        "<tr><td>1</td><td>CEILING PRICES (As On 30.09.2020)</td>"
        "<td><a href='https://nppa.gov.in/storage/uploads/pdf/Ceiling-List-2a92c4.pdf'>934KB/PDF</a></td></tr>",
        "<tr><td>2</td><td>CEILING PRICES (As On 30.11.2014)</td>"
        "<td><a href='ceilingpricesason30.11.2014'>View</a></td></tr>",  # an NPPA page: the data
        "<tr><td>3</td><td>Compendium of Prices 2026</td>"
        "<td><a href='https://nppaipdms.gov.in/dashboard'>View</a></td></tr>",  # off-site
        "<tr><td>4</td><td>NOTIFICATIONS – YEAR 2013</td></tr>",  # no Download cell at all
    )

    documents, skipped = reference_documents(page, PAGE_URL, "dpco2013")

    assert [(d.file_type, d.prefix, d.url) for d in documents] == [
        (
            "pdf",
            "nppa/dpco2013/ceiling-list-2a92c4",
            "https://nppa.gov.in/storage/uploads/pdf/Ceiling-List-2a92c4.pdf",
        ),
        (
            "html",
            "nppa/dpco2013/ceilingpricesason30-11-2014",
            "https://nppa.gov.in/en/ceilingpricesason30.11.2014",
        ),
    ]
    assert [reason.split(":")[0] for _, reason in skipped] == [
        "links off-site",
        "no link on the page",
    ]


def test_orders_are_filed_by_month():
    page = orders_page(
        "<tr><td>1</td><td>04-Nov-2026</td><td>Notification for retail price fixation</td>"
        "<td><a href='/storage/uploads/tender/retail-04-11-2026.pdf'>0.78 MB PDF</a></td></tr>"
    )

    [order] = order_documents(page, "https://nppa.gov.in/en/view_more?id=4")

    assert order.prefix == "nppa/orders/2026-11/retail-04-11-2026"
    assert order.url == "https://nppa.gov.in/storage/uploads/tender/retail-04-11-2026.pdf"
    assert order.order_date.isoformat() == "2026-11-04"


@pytest.mark.parametrize(
    ("finder", "page", "message"),
    [
        (
            lambda p: reference_documents(p, PAGE_URL, "x"),
            "<p>maintenance</p>",
            "no 'Document Name'",
        ),
        (lambda p: order_documents(p, PAGE_URL), "<p>maintenance</p>", "no orders table"),
        (
            lambda p: order_documents(p, PAGE_URL),
            orders_page(
                "<tr><td>1</td><td>04/11/2026</td><td>T</td><td><a href='a.pdf'>x</a></td></tr>"
            ),
            "unexpected date",
        ),
        (
            lambda p: order_documents(p, PAGE_URL),
            orders_page("<tr><td>1</td><td>04-Nov-2026</td><td>T</td><td>no file</td></tr>"),
            "unexpected order row",
        ),
    ],
)
def test_a_changed_page_stops_the_run(finder, page, message):
    with pytest.raises(UnexpectedResponseError, match=message):
        finder(page)


@pytest.fixture
def nppa(http_server, fake_clock, raw_store) -> Nppa:
    fetcher = PoliteFetcher(clock=fake_clock.time, sleep=fake_clock.sleep)
    return Nppa(fetcher, raw_store, site_url=http_server.base_url)


def serve_dpco(http_server, pdf: bytes = FAKE_PDF, data_page: bytes = FAKE_DATA_PAGE):
    page = reference_page(
        "<tr><td>1</td><td>CEILING PRICES (As On 30.09.2020)</td>"
        "<td><a href='/storage/uploads/pdf/ceiling-list.pdf'>934KB/PDF</a></td></tr>",
        "<tr><td>2</td><td>CEILING PRICES (As On 30.11.2014)</td>"
        "<td><a href='list-2014'>View</a></td></tr>",
    )
    http_server.scripts[REFERENCE_PATHS["dpco2013"]] = [(200, page.encode())]
    http_server.scripts["/storage/uploads/pdf/ceiling-list.pdf"] = [(200, pdf)]
    http_server.scripts["/en/list-2014"] = [(200, data_page)]


def test_downloads_pdfs_and_data_pages_with_their_listing_details(nppa, http_server):
    serve_dpco(http_server)
    documents, _ = nppa.list_documents(["dpco2013"])

    pdf, page = (nppa.download(doc) for doc in documents)

    assert pdf.key.startswith("nppa/dpco2013/ceiling-list/") and pdf.key.endswith(".pdf")
    assert page.key.startswith("nppa/dpco2013/list-2014/") and page.key.endswith(".html")
    assert nppa.store.s3.objects[page.key] == FAKE_DATA_PAGE  # stored exactly as received
    sidecar = json.loads(nppa.store.s3.objects[pdf.key + ".meta.json"])
    assert sidecar["title"] == "CEILING PRICES (As On 30.09.2020)"
    assert sidecar["listing"]["size_text"] == "934KB/PDF"
    assert sidecar["order_date"] is None


def test_a_stored_document_is_skipped_without_a_request(nppa, http_server):
    serve_dpco(http_server)
    documents, _ = nppa.list_documents(["dpco2013"])
    nppa.download(documents[0])
    requests_before = len(http_server.requests)

    assert nppa.download(documents[0]).outcome == "skipped"
    assert len(http_server.requests) == requests_before


def test_an_error_page_instead_of_a_pdf_stores_nothing(nppa, http_server):
    serve_dpco(http_server, pdf=b"<html>Error</html>")
    pdf_document, _ = nppa.list_documents(["dpco2013"])[0]

    with pytest.raises(UnexpectedResponseError, match="not a PDF"):
        nppa.download(pdf_document)

    assert nppa.store.s3.objects == {}


def test_a_data_page_without_its_table_stores_nothing(nppa, http_server):
    serve_dpco(http_server, data_page=b"<html><p>Page moved</p></html>")
    _, page_document = nppa.list_documents(["dpco2013"])[0]

    with pytest.raises(UnexpectedResponseError, match="no longer has a data table"):
        nppa.download(page_document)

    assert nppa.store.s3.objects == {}


def test_rejects_an_unknown_section(nppa):
    with pytest.raises(ValueError, match="section must be one of"):
        nppa.list_documents(["prices"])


def test_orders_path_is_fetched_for_the_orders_section(nppa, http_server):
    http_server.scripts[ORDERS_PATH.split("?")[0]] = [
        (
            200,
            orders_page(
                "<tr><td>1</td><td>04-Nov-2026</td><td>Order</td>"
                "<td><a href='/storage/uploads/tender/order-1.pdf'>1 MB</a></td></tr>"
            ).encode(),
        )
    ]

    documents, skipped = nppa.list_documents(["orders"])

    assert [d.prefix for d in documents] == ["nppa/orders/2026-11/order-1"]
    assert http_server.requests[0]["path"] == ORDERS_PATH
