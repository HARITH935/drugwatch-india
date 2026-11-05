"""CDSCO legacy PDF adapter: title parsing on real title variants, and the two-hop download
against a fake CDSCO site on localhost (made-up PDFs, no real alert data)."""

import base64
import json

import pytest

from drugwatch_ingestion.fetcher import PoliteFetcher
from drugwatch_ingestion.sources import UnexpectedResponseError
from drugwatch_ingestion.sources.cdsco_pdf import CdscoPdf, classify_title, find_documents

LISTING_PATH = "/opencms/opencms/en/Notifications/Alerts/"
JSP_PATH = "/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp"
PDF_PATH = "/opencms/resources/UploadCDSCOWeb/2018/UploadAlertsFiles/Test NSQ june25.pdf"
FAKE_PDF = b"%PDF-1.4 made-up test file"


@pytest.mark.parametrize(
    ("title", "expected"),
    [  # Real title variants from the CDSCO alerts table (2017-2025)
        ("CDSCO NSQ ALERT FOR THE MONTH OF June 2025", ("central-nsq", "2025-06")),
        ("STATE NSQ ALERT FOR THE MONTH OF MAY-2025", ("state-nsq", "2025-05")),
        ("State NSQ Alert For The Month April-2025", ("state-nsq", "2025-04")),
        ("List of spurious Drugs for the month of June-2025", ("spurious", "2025-06")),
        ("NSQ ALERT FOR THE MONTH OF Feb-2025", ("central-nsq", "2025-02")),
        ("NSQ ALERT FOR THE MONTH OF JUlY-2024", ("central-nsq", "2024-07")),
        ("NSQ May 2024 State Labs", ("state-nsq", "2024-05")),
        ("NSQ May 2024 CDSCO Labs", ("central-nsq", "2024-05")),
        ("NOT OF STANDARD QUALITY ALERT FOR THE MONTH OF MAR-2022", ("central-nsq", "2022-03")),
        (
            "Not Of Standard of Quality (NSQ) ALERT FOR THE MONTH OF April-2025",
            ("central-nsq", "2025-04"),
        ),
        (
            "List of Drugs Medical Devices Vaccine and Cosmetics declared as Spurious for the "
            "Month of March- 2025",
            ("spurious", "2025-03"),
        ),
        (  # "declared" starts with "dec": must not be read as December
            "List of Drugs Medical Devices Vaccine and Cosmetics declared as Spurious Adulterated "
            "Misbranded for the Month of August-2024",
            ("spurious", "2024-08"),
        ),
        (
            "List of Drugs, Medical Devices and Cosmetics declared as Not of Standard Quality/"
            "Spurious/Adulterated/Misbranded, For the Month of August, 2018",
            ("combined", "2018-08"),
        ),
        (  # mis-decoded en dash between month and year, exactly as on the live page
            "List of Drugs, Medical Devices, Vaccine and Cosmetics declared as Not of Standard "
            "Quality/Spurious/Adulterated/Misbranded for the Month of "
            "Januaryâ\x80\x93 2025 Revised",
            ("combined", "2025-01"),
        ),
        ("Samples declared NSQ 2017-2023", ("nsq-bulk", None)),
        ("Availability of Not Standard Quality (NSQ) Alert on New Link in CDSCO Website", None),
        ("NSQ of Typhoid Polysaccharide Vaccine TYPBAR", None),
        (
            "NSQ Vi-Conjugate Typhoid Vaccine Batch No.TC010915 and Batch No. TC010417 of "
            "M/s Bio Med Pvt Ltd dated 14-03-2018",
            None,
        ),
        (
            "Guidelines for taking action on samples of drugs declared spurious or not of standard",
            None,
        ),
        ("Circular to all State/UT Licensing Authorities regarding revised GST rates", None),
    ],
)
def test_classify_title(title, expected):
    assert classify_title(title) == expected


def listing(*rows: tuple[str, str, str]) -> bytes:
    """A made-up alerts page shaped like the real one: (title, release date, file id) per row."""
    cells = "".join(
        f"<tr><td>{n}</td><td>{title}</td><td>{released}</td>"
        f"<td><a href='{JSP_PATH}?num_id={base64.b64encode(file_id.encode()).decode()}'>"
        f"<i class='fa fa-file-pdf-o'></i></a></td><td>185 KB</td></tr>"
        for n, (title, released, file_id) in enumerate(rows, start=1)
    )
    return (
        "<html><body><div class='sidebar'><a href='/elsewhere'>Alerts</a></div>"
        "<table class='table' id='example'><tr><th>S.no</th><th>Title</th><th>Release Date</th>"
        f"<th>Download Pdf</th><th>Pdf Size</th></tr>{cells}</table></body></html>"
    ).encode()


JUNE = ("CDSCO NSQ ALERT FOR THE MONTH OF June 2025", "2025-Jul-18", "12927")


def test_find_documents_keeps_lists_and_reports_skipped_rows():
    page = listing(
        JUNE,
        ("Circular regarding revised GST rates", "2025-Oct-08", "13487"),
        ("NSQ of Typhoid Polysaccharide Vaccine TYPBAR", "2023-Jun-08", "10000"),
        ("Samples declared NSQ 2017-2023", "2024-Sep-11", "11955"),
    ).decode()

    documents, skipped = find_documents(page)

    assert [(d.file_id, d.kind, d.prefix) for d in documents] == [
        ("12927", "central-nsq", "cdsco-pdf/central-nsq/2025-06/12927"),
        ("11955", "nsq-bulk", "cdsco-pdf/nsq-bulk/2017-2023/11955"),
    ]
    assert [row.title for row in skipped] == ["NSQ of Typhoid Polysaccharide Vaccine TYPBAR"]


def test_a_month_that_does_not_fit_the_release_date_is_skipped_not_misfiled():
    page = listing(("NSQ ALERT FOR THE MONTH OF MAY-2026", "2025-Jun-20", "1")).decode()

    documents, skipped = find_documents(page)

    assert documents == []
    assert "doesn't fit release date" in skipped[0].reason


@pytest.mark.parametrize(
    ("page", "message"),
    [
        ("<html><p>Site under maintenance</p></html>", "no rows"),
        (
            "<table id='example'><tr><td>1</td><td>NSQ</td><td>2025-Jul-18</td></tr></table>",
            "unexpected row",
        ),
        (listing(("NSQ ALERT FOR THE MONTH OF May-2025", "18/07/2025", "1")).decode(), "date"),
    ],
)
def test_a_changed_listing_stops_the_run(page, message):
    with pytest.raises(UnexpectedResponseError, match=message):
        find_documents(page)


@pytest.fixture
def cdsco(http_server, fake_clock, raw_store) -> CdscoPdf:
    fetcher = PoliteFetcher(clock=fake_clock.time, sleep=fake_clock.sleep)
    return CdscoPdf(fetcher, raw_store, listing_url=http_server.base_url + LISTING_PATH)


def serve_site(http_server, *, hop_page: bytes | None = None, pdf: bytes = FAKE_PDF):
    """Script the fake site: listing -> .jsp page with an <iframe> -> PDF (path has spaces)."""
    hop = hop_page or f"<html><iframe src='{PDF_PATH}' width='100%'></iframe></html>".encode()
    http_server.scripts[LISTING_PATH] = [(200, listing(JUNE))]
    http_server.scripts[JSP_PATH] = [(200, hop)]
    http_server.scripts[PDF_PATH.replace(" ", "%20")] = [(200, pdf)]  # requests encodes spaces


def test_two_hop_download_stores_the_pdf_with_listing_metadata(cdsco, http_server):
    serve_site(http_server)
    documents, _ = cdsco.list_documents()

    result = cdsco.download(documents[0])

    assert result.outcome == "stored"
    assert result.key.startswith("cdsco-pdf/central-nsq/2025-06/12927/")
    assert cdsco.store.s3.objects[result.key] == FAKE_PDF
    sidecar = json.loads(cdsco.store.s3.objects[result.key + ".meta.json"])
    assert sidecar["file_id"] == "12927"
    assert sidecar["alert_month"] == "2025-06"
    assert sidecar["listing"]["title"] == JUNE[0]
    assert sidecar["listing"]["release_date"] == "2025-07-18"
    assert sidecar["first_hop_url"].endswith("num_id=MTI5Mjc=")
    assert sidecar["request"]["final_url"].endswith("/Test%20NSQ%20june25.pdf")
    assert [r["path"].split("?")[0] for r in http_server.requests] == [
        LISTING_PATH,
        JSP_PATH,
        PDF_PATH.replace(" ", "%20"),
    ]


def test_a_stored_document_is_skipped_without_requests(cdsco, http_server):
    serve_site(http_server)
    documents, _ = cdsco.list_documents()
    cdsco.download(documents[0])
    requests_before = len(http_server.requests)

    again = cdsco.download(documents[0])

    assert again.outcome == "skipped"
    assert len(http_server.requests) == requests_before


@pytest.mark.parametrize(
    ("site", "message"),
    [
        ({"hop_page": b"<html><p>File not found</p></html>"}, "no <iframe src>"),
        ({"pdf": b"<!DOCTYPE html><html>Error</html>"}, "not a PDF"),
    ],
)
def test_a_broken_download_stores_nothing(cdsco, http_server, site, message):
    serve_site(http_server, **site)
    documents, _ = cdsco.list_documents()

    with pytest.raises(UnexpectedResponseError, match=message):
        cdsco.download(documents[0])

    assert cdsco.store.s3.objects == {}
