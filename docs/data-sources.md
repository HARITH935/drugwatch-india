# Data sources

> Living document, filled in during Phase 1. Status: **Phase 1 steps 1–6 done** (sources located, terms read,
> everything downloaded incl. the manual NPPA 2026 export; raw layout in §6; what's inside the files in §7).
> All findings below were checked on **2026-11-04**.

---

## 1. CDSCO NSQ / spurious drug alerts

CDSCO publishes these alerts in **two places**. In August 2025 it moved them from PDF files to an online portal:

| | Legacy PDF list | NSQ portal |
|---|---|---|
| Host | `cdsco.gov.in` | `cdscoonline.gov.in` |
| Format | PDF, one file per month per source | JSON, served from a search page |
| Central (CDSCO labs) NSQ | 2017–2023 scattered, Apr 2024 – Jun 2025 (with a gap) | Jan 2019 – Sep 2026 |
| State labs NSQ | May 2024 – Jun 2025 (with a gap) | Jan 2019 – Sep 2026 (same endpoint, `source=State`) |
| Spurious | Apr 2024 – Jun 2025 (with gaps) | 2025 – 2026 |
| Still updated? | No. Last entry 2025-08-28 announces the move to the "new link" | Yes |

### 1a. Legacy PDF list (`cdsco.gov.in`)

**Listing page:** https://cdsco.gov.in/opencms/opencms/en/Notifications/Alerts/
(`/opencms/opencms/en/Alerts/` serves the same table.)

- The page returns **all 300 rows in one HTML response** (Feb 2010 – Sep 2026, every type of alert, not only NSQ).
  The "pages" a browser shows come from the DataTables JavaScript library, so a scraper doesn't need to handle pagination.
- Columns: S.No · title · posted date (`YYYY-Mon-DD`) · download link · file size.
- About 50 of the 300 rows are NSQ or spurious related. The rest are circulars, guidelines and similar.
  Some NSQ-titled rows aren't monthly lists either (guidelines, single-product alerts), so filtering by keyword alone isn't enough.

**Getting a file takes two hops:**

1. Each row links to
   `/opencms/opencms/system/modules/CDSCO.WEB/elements/download_file_division.jsp?num_id=<id>`
   where `<id>` is a **numeric file ID in base64** (`MTI5Mjc=` → `12927`).
2. That URL returns a ~150-byte HTML page with an `<iframe>` whose `src` is the real file, e.g.
   `/opencms/resources/UploadCDSCOWeb/2018/UploadAlertsFiles/CDSCO NSQ june25.pdf`

Quirks:
- **File names are free text**, with spaces and no fixed pattern (`CDSCO NSQ june25.pdf`,
  `NSQ Alert For The Month of March-2025.pdf`, `NSQ ALERT FOR THE MONTH OF October-2024 for website.pdf`).
  Don't build file URLs from a pattern. Discover them from the listing.
- **Titles are inconsistent** too (`NSQ ALERT FOR THE MONTH OF Feb-2025`, `NSQ May 2024 CDSCO Labs`,
  `Not Of Standard of Quality (NSQ) ALERT FOR THE MONTH OF April-2025`). The alert month has to be parsed
  from the title. The posted date is usually about a month later.
- The `.jsp` hop's `Last-Modified` header is the **current time** on every request, so it can't be used to detect changes.
  The real PDF *does* send a proper `ETag` and `Last-Modified` (June 2025 file: `Last-Modified: Fri, 18 Jul 2025`).
- **The listing is incomplete.** No central NSQ PDF is listed for Aug–Dec 2024, but at least
  `NSQ ALERT FOR THE MONTH OF October-2024 for website.pdf` exists on the server (found by web search).
  We also checked Latest Alerts (newest 10 only), Archive (no NSQ entries), Consumer, and the sidebar
  widget on every page. None of them list the missing months.
- One bulk file may cover the history: **"Samples declared NSQ 2017-2023"** (file ID 11955, posted 2024-09-11). Not yet opened.
- Every page has a scrolling "Alerts" sidebar widget with 225 links that duplicate the table. A scraper should ignore it.
- **What the adapter keeps** (step 4c, listing of 2026-11-05): **44 documents**: 21 central NSQ, 9 state NSQ,
  10 spurious, 3 combined NSQ/spurious lists and the bulk 2017-2023 file. It skips 7 NSQ/spurious rows that
  aren't monthly lists (the "new link" notice, three single-product alerts, guidelines, a whistle-blower
  scheme, a 2010 survey); `--list` prints them with the reason.
- One title contains mis-decoded characters: "Januaryâ\x80\x93 2025 Revised" (an en dash, double-encoded).

Monthly NSQ lists found on the listing page (central = CDSCO labs):

| Type | Months |
|---|---|
| Central NSQ | Jul 2017, Sep 2017, Jan 2018, Feb 2018, Apr 2018, Sep 2018, Mar 2019, Apr 2019, Mar 2022, Jun 2022, Apr 2023, Apr–Jul 2024, Jan–Jun 2025 |
| State NSQ | May–Jul 2024, Jan–Jun 2025 |
| Combined NSQ/spurious lists | two in 2018 (posted Jun and Sep 2018), Jan 2025 "Revised" |
| Spurious | Apr 2024, then lists posted Sep–Dec 2024 and Mar–Jul 2025 |

### 1b. NSQ portal (`cdscoonline.gov.in`): the current source

**Page:** https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/ embeds an iframe from
https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug

The portal publishes **no PDFs**. Its page calls JSON endpoints (all `GET`, no login):

| Endpoint | Parameters | Returns |
|---|---|---|
| `/CDSCO/reportingYears` | `tab=nsq` or `tab=spurious` | list of years |
| `/CDSCO/publicReportingMonths` | `year=YYYY`, `tab=` | list of month abbreviations (`"Jan"`, …) |
| `/CDSCO/filteredNsqDrugTable` | `month=Mon-YYYY`, `source=All\|State\|CDL`, `tab=nsq` | `{iTotalRecords, iTotalDisplayRecords, aaData: [...]}` |
| `/CDSCO/filteredSpuriousDrugTable` | same as above, `tab=spurious` | same shape |
| `/CDSCO/publicNsqDrugTable` | none | default table (**not called yet**: size unknown) |
| `/CDSCO/viewPublicSpuriousDrugData` | none | default spurious table (not called yet) |
| `/CDSCO/statesPendingSubmission` | `month=Mon-YYYY` | states that have not yet submitted for that month |

Coverage reported by the portal: **NSQ 2019 – 2026** (2026 up to Sep), **spurious Jun 2025 – Sep 2026** (15 months in its menus).

**Full download (step 5a, 2026-11-05):** 93 NSQ months, **6,956 rows**; 15 spurious months, **49 rows**; no empty months.

| NSQ rows | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (Jan–Sep) |
|---|---|---|---|---|---|---|---|---|
| | 404 | 326 | 345 | 572 | 644 | 877 | 1,898 | 1,890 |

The jump from 2025 matches state labs reporting through the portal (Mar-2025: 61 of 131 rows from state labs).
More rows mean **more reporting**, not necessarily worse medicines: keep that in mind for every chart and for the
risk score (CLAUDE.md §6).
Sampled months return real rows:

| Month | Rows | By source |
|---|---|---|
| Jan-2019 | 45 | CDSCO lab 37, State lab 8 |
| Jun-2022 | 28 | CDSCO lab 15, State lab 13 |
| Mar-2025 | 131 | CDSCO lab 70, State lab 61 |
| Sep-2026 | 330 | State lab 235, State Lab 53, CDSCO Labs 42 |

**NSQ row fields:**

| Field | Example | Notes |
|---|---|---|
| `str_product_name` | `Alprazolam Tablets IP 0.5 mg` | generic name |
| `str_brand_name` | `Alzomac-0.5 Tablets` | |
| `str_batch_no` | `60098` | no blanks in Sep-2026 sample |
| `dt_manufacturing_date` | `Feb-2026` | month precision only |
| `dt_expiry_date` | `Jan-2028` | month precision only |
| `str_manufactured_by` | `Uniza Lifecare Pvt. Ltd.  , Sr. No. 919/7, …, Gujarat-382715, India.` | **name and full address in one string** |
| `str_nsq_result` | `The sample does not conform to IP in respect of Dissolution` | free text |
| `str_reporting_source` | `State lab` | see quirks |
| `str_reported_by_lab_or_state` | `LUCKNOW, Uttar Pradesh` | |
| `dt_reporting_month_year` | `SEP-2026` | upper case (request uses `Sep-2026`) |

Spurious rows use different field names (from the page's JavaScript; **confirmed** on the real Sep-2026 table, step 4c):
`product_name_from_dtl`, `str_brand_name`, `str_batch_no`, `dt_manufacturing_date`, `dt_expiry_date`,
`str_spurious_manufacturer_name`, `str_spurious_manufactured_by`, `str_reporting_source`,
`str_reported_by_lab_or_state`, `dt_reporting_month_year`, `str_nsq_remarks`, `str_firm_reply`.

Quirks:
- **Encoding:** responses aren't valid UTF-8 (byte `0xAE`, i.e. `®`). We decode as **Windows-1252 (cp1252)**.
  The server itself declares `Content-Type: text/plain;charset=ISO-8859-1`. The two differ only for bytes
  `0x80`–`0x9F`, and none appear in any sample (2019–2026: the only non-ASCII byte is one `0xAE`), so both give
  the same text. Bronze (Phase 3) should decode strictly and fail loudly on a byte cp1252 doesn't define.
- **Source labels change over time:** `CDSCO lab` (2019–2025 samples) vs `CDSCO Labs` (Sep 2026); `State lab` vs `State Lab`.
- `publicReportingMonths` returns Jan–Dec for every full year, so it doesn't prove a month has data. Check the row count.
- No row has a link to an original document. Provenance for portal rows is the request URL plus the download time.
- No `ETag` or `Last-Modified` headers, so the only way to detect a change is to download and compare hashes.
  (Sep-2026 fetched on 2026-11-04 and 2026-11-05 was byte-identical.)

---

## 2. NPPA ceiling prices

NPPA (National Pharmaceutical Pricing Authority) sets **ceiling prices**: the legal maximum price, before GST,
for scheduled formulations under DPCO 2013. Scheduled formulations are the medicines on the National List
of Essential Medicines (NLEM 2011 / 2015 / 2022).

**Hosts:**
- `nppa.gov.in` is the main site. The old `nppaindia.nic.in` no longer resolves in DNS.
  **Its HTTPS chain is incomplete:** the server leaves out the Sectigo "Public Server Authentication CA DV R36"
  intermediate, so Python fails with `CERTIFICATE_VERIFY_FAILED`. We supply that intermediate (ADR 0006).
  The site's certificate expires **2026-11-18**: if the renewal changes the chain, add the new intermediate.
- `nppaipdms.gov.in` hosts NPPA's applications (IPDMS = Integrated Pharmaceutical Database Management System).

NPPA's data is spread over five places, none of which is one clean, current, bulk source:

| # | Source | Coverage | Format | Bulk-downloadable by script? |
|---|---|---|---|---|
| a | Compendium of Prices | 2016, 2022 (PDF); **2026 (dashboard)** | PDF; dashboard with CSV export | PDFs yes; 2026 CSV is browser-only (see below) |
| b | Consolidated ceiling-price lists | as on 30.11.2014, 13.08.2018, 30.09.2020 | PDF | yes |
| c | Therapeutic-category lists | 5 categories, undated | PDF | yes |
| d | Circulars / Orders feed | 06-Jan-2026 – today only | one PDF per order | yes |
| e | Pharma Sahi Daam search | current; also **branded MRPs** | JSON behind request signing | **no**: off-limits (see below) |

**a. Compendium of Prices:** https://nppa.gov.in/en/compendiumofprice
- `Compendium of Prices 2016` (175 KB PDF) and `Updated till 10.08.2022` (1 MB PDF), e.g.
  `/storage/uploads/pdf/Compendium-Prices-2022pdf-464b22085495ff4e3f8700c0e00cf45d.pdf`
- `Compendium of Prices 2026` links to an IPDMS **dashboard**
  (`nppaipdms.gov.in/HISUtilities/dashboard/dashBoardACTION.cnt?...`). It shows "All Drugs Ceiling Prices",
  can filter by NLEM version (2011 / 2015 / 2022 / All), and has **Download CSV** and **Download PDF** buttons.
  This is the best current consolidated list. The dashboard loads `crypto-js` and runs on the same framework
  as Pharma Sahi Daam, so scripted access probably meets the same request signing (not tested).
  A person clicking "Download CSV" in a browser is the intended use.
- **Collected (manual drop, ADR 0003):** the dashboard's **Download PDF** export, "All Drugs Ceiling Prices", NLEM version
  **All**, 60 text pages (made with iText), printed 05/11/2026 09:56. Columns: SL No · NLEM Version · Formulation ·
  Dosage & Strength · SO Number · SO Date · Ceiling Price (Excluding Taxes) (Rs.)(Per Unit). Row numbers restart per
  NLEM version, and the rupee sign appears as the literal text `&#8377`. Stored under `nppa/compendium-2026/2026-11`.
  A CSV export of the same list would save Phase 3 a PDF parse; optional.

**b. Consolidated lists:** https://nppa.gov.in/en/dpco2013
- `CEILING PRICES OF SCHEDULED FORMULATIONS UNDER DPCO, 2013` as on **30.09.2020** (934 KB), **13.08.2018** (131 KB),
  30.11.2014 (sub-page), plus 2013/2014 notification lists and retail-price lists for new drugs.
- **The four 2014 rows link to NPPA pages, not PDFs: the page's HTML table *is* the data** (30.11.2014
  consolidated list ≈ 396 rows, 2014 notifications ≈ 550, new-drug retail prices 81, Para 19 MRPs 113).
  The adapter stores those pages as `.html`. The two 2013 rows have no link at all.
- `LIST OF REVISED MRP OF ANTI-CANCER MEDICINES UNDER TMR APPLICABLE FROM 8th MARCH, 2019`: 526 **brand** MRPs
  (TMR = Trade Margin Rationalisation).

**c. Therapeutic-category lists:** https://nppa.gov.in/en/therapeuticcategorywiseceilingpricelist
- Undated PDFs: Anti-Cancer (131 formulations), Anti-Diabetes (11), Anti-HIV (29), Anti-TB (30), Cardio-Vascular (66).
  The file names (`2845-fb-posts-...`) suggest they were made for social media.

**d. Circulars / Orders feed:** https://nppa.gov.in/en/view_more?id=4
- All rows come in one HTML response (DataTables, as on CDSCO). It held **153 rows, all from 2026** (154 on 2026-11-05)
  (06-Jan-2026 → 03-Nov-2026); older orders aren't listed here.
- By title: 93 draft price worksheets, 23 ceiling-price orders, 16 retail-price orders for new drugs,
  5 MRP lists, 5 exemptions, 11 other.
- Files: `/storage/uploads/tender/<slug>-DD-MM-YYYY.pdf`, e.g. `review-04-11-2026.pdf`.
  Useful for picking up *changes*, not as a full list.

**e. Pharma Sahi Daam:** https://nppaipdms.gov.in/NPPA/PharmaSahiDaam/searchMedicine
(linked from https://nppa.gov.in/en/pharma_sahi_daam)
- Two modes: "Search Medicine Price" (by brand or formulation, giving **branded MRPs**) and
  "Ceiling Prices of Essential Medicines".
- REST endpoints under `/NPPA/rest/`. One list endpoint answers a plain `GET`:
  `scheduledFormulationComboNew` returns **437 scheduled formulations** as `{schFormulationId, schFormulationName}`.
- The data endpoints (`schFormDataTableNew`, `brandDataTableNew`, `formulationDataTableNew`, `ceilingPriceDtlsNew`, …)
  return `404 "Something went wrong"` to direct calls. The page passes every data URL through
  `createFHashAjaxQuery()`, commented in their code as a *"security feature added on 28/07/2017"*.
- **Decision: we do not reverse-engineer this.** Getting around a deliberate access control breaks our
  scraping etiquette (CLAUDE.md §7), whatever the data.
- File names under `/storage/uploads/pdf/` end in a 32-hex-character hash, so they can't be predicted.
  Discover them from the listing pages.

**What the adapter keeps** (step 4c, pages of 2026-11-05): **168 documents**: Compendium 2 PDFs (2016, 2022);
DPCO 2013 3 PDFs (2018 and 2020 lists, 526 anti-cancer brand MRPs) + 4 HTML data pages (2014);
category lists 5 PDFs; orders feed 154 PDFs (Jan–Nov 2026). Skipped: the 2026 dashboard (off-site: manual
drop) and the two link-less 2013 rows. NPPA HTML pages change on every visit (CSRF token, visitor counter),
so they're never byte-identical: stored pages are skipped, and `--refresh` would store a new version each time.

## 3. Jan Aushadhi product list

Jan Aushadhi (PMBJP) is the government's chain of low-cost generic medicine stores, run by PMBI
(Pharmaceuticals & Medical Devices Bureau of India). A 2025 government document gives the range as about
2,047 medicines and 300 surgical items.

**Hosts:**
- `janaushadhi.gov.in` is a **React single-page app (SPA)**. Every unknown path returns the homepage
  HTML with HTTP 200, so always check `Content-Type` and never trust the status code alone.
- `janaushadhi.gov.in:8443` is the site's JSON API.
- `pmbi.co.in` holds old files only.

**Public page:** https://janaushadhi.gov.in/product-portfolio/product-mrp-list ("Product & MRP List"; also `product-view-List`).

**API behind it** (read from the page's JavaScript bundle `static/js/main.*.js` and chunk `7204.*.chunk.js`):

| | |
|---|---|
| Endpoint | `POST https://janaushadhi.gov.in:8443/api/v1/website/getAllProductForWeb` |
| Body | `{"pageIndex": 0, "pageSize": N, "searchText": "", "columnName": "drug_code", "orderBy": "asc"}` |
| Response | `{responseCode, responseBody: {totalElement, newProductResponsesList: [...]}}`; the page shows rows with `status == 1` |
| Whole list | The page's own export asks for `pageSize: 1000000`, i.e. everything in one request |
| Auth | `Authorization: Bearer <guest token>`. For anonymous visitors the page first calls `GET :8443/auth/generateGuestToken`, keeps the token until its JWT `exp`, then fetches a new one |

- Without the guest token the API returns a generic `HTTP 500` (tested with two requests).
  Using the guest token was approved in step 3 (ADR 0003: every anonymous visitor gets one).
- **Guest token response** (verified 2026-11-05): `{"responseBody": "<JWT>", "message", "responseCode"}`.
  The adapter checks it is JWT-shaped before putting it in a header, and never stores or logs it.
- `/api/v1/admin/...` endpoints (add/delete products, CSV upload, PDF export) also exist. They belong to the
  admin panel and are **off-limits**.
- Old static file `janaushadhi.gov.in/data/MRPList.pdf` is **gone** (returns the SPA fallback page).
- Historical lists cited by search results: `pmbi.co.in/old-data/PriceListMay2014.pdf`, `PriceListDec2014.pdf` (not fetched).
- Unofficial copies exist (sarkariyojana.com, Scribd). They're **not used**: not official, and no provenance.
- **Product fields** (verified 2026-11-05): `productId`, `genericName`, `groupName`, `drugCode`, `unitSize`, `mrp`,
  `status`, `serialNo` (row number only).
- **Snapshot of 2026-11-05:** 2,453 products in one response (`totalElement` = 2,453), all `status 1`, 470 KB.
  319 are "Surgical & Medical Consumables". `drugCode` has no duplicates, so it's a usable key.
- **Quirk: `mrp` is 0 for 353 products (14%)**, spread across almost every group. Most likely "price not set",
  not free. Phase 3 should treat 0 as missing, never as a real price of ₹0.

---

## 4. robots.txt and terms of use

Checked 2026-11-04. Quotes are copied from each site's policy pages. *This is our reading, not legal advice.*

### 4.1 robots.txt

| Host | robots.txt |
|---|---|
| `cdsco.gov.in` | 404 (none published) |
| `cdscoonline.gov.in` | 404 (none published) |
| `nppa.gov.in` | **403 Forbidden** (unreadable; the homepage itself loads fine) |
| `nppaipdms.gov.in` | 404 (none published) |
| `janaushadhi.gov.in` | none (the SPA returns its homepage HTML for `/robots.txt`) |
| `pmbi.co.in` | 404 (none published) |

No `robots.txt` means no crawl rules are published. We still rate-limit every request (CLAUDE.md §7).
An unreadable `robots.txt` (NPPA, 403) is treated cautiously: listing pages and published PDFs only.

### 4.2 Terms of use

| Owner (hosts) | Reproducing content | Linking to the site | Framing | Policy pages |
|---|---|---|---|---|
| **CDSCO** (`cdsco.gov.in`, `cdscoonline.gov.in`) | **Needs permission**: "may not be reproduced partially or fully, without due permission from Central Drugs Standard Control Organization"; source "must be appropriately acknowledged"; not "in any misleading or objectionable context" | **Contradictory**: Terms page says "no prior permission is required" (but asks to be informed); Disclaimer says "Prior permission is required before hyperlink are directed … to this site" | Not allowed | [Copyright](https://cdsco.gov.in/opencms/opencms//en/Copyright-Policy/), [Terms](https://cdsco.gov.in/opencms/opencms/en/terms_conditions/), [Disclaimer](https://cdsco.gov.in/opencms/opencms/en/disclaimer/) |
| **NPPA** (`nppa.gov.in`, `nppaipdms.gov.in`) | **Free, no permission needed**: "may be reproduced free of charge in any format or media without requiring specific permission", if accurate, not derogatory or misleading, and "the source must be prominently acknowledged" | No permission needed (they ask to be informed) | Not allowed | [Copyright](https://nppa.gov.in/en/copyrightpolicy), [Hyperlink](https://nppa.gov.in/en/hyperlinkingpolicy), [Terms](https://nppa.gov.in/en/termsconditions) |
| **PMBI / Jan Aushadhi** (`janaushadhi.gov.in`, `pmbi.co.in`) | **Needs permission**: "may be reproduced free of charge after taking proper permission by sending a mail to us"; accurate, source "prominently acknowledged" | **Prior permission required** | (not stated) | Copyright / Hyperlink / Disclaimer sections of the site (text is in the SPA bundle) |

Other points:
- **No site restricts automated access.** None of the policy pages mention bots, crawlers, scraping or bulk downloads.
  The terms govern **republishing**, not **fetching**.
- **All three say their content is not a statement of law.** NPPA: prices "should not be construed as a statement
  of law or used for any legal purposes"; Jan Aushadhi says the same. Our price pages must say prices are for information only.
- **No framing anywhere:** the site must link to source documents (opening in a new tab), never embed them in an iframe.
  This affects Phase 11.

### 4.3 What this means for the project

| Activity | Allowed now? | Why |
|---|---|---|
| Downloading public pages and files for analysis (Phase 1 steps 4–5 and later) | Yes | Not restricted by any terms; we rate-limit and respect robots.txt |
| Publishing NPPA prices on the live site | Yes, with prominent attribution | NPPA grants reproduction without permission |
| Publishing CDSCO NSQ data on the live site | **Only after permission** | CDSCO copyright policy |
| Publishing Jan Aushadhi prices on the live site | **Only after permission** | PMBI copyright policy ("sending a mail to us") |
| Linking to original CDSCO / Jan Aushadhi documents | Ask in the same permission request | CDSCO's pages contradict each other; Jan Aushadhi requires permission |

Permission is needed **before public launch (Phase 12)**, not before downloading. Government replies can be slow, so ask early.

During discovery: ≥3 s between requests, User-Agent `DrugWatchIndia-research/0.1`, about 65 requests in total
across all hosts (step 1: ~25, step 2: ~30, step 3: ~7).

---

## 5. Open questions

1. ~~Which CDSCO source is primary?~~ **Decided (ADR 0004):** portal JSON from 2019; PDFs kept for 2017–2018 and Phase 2.
2. **Do the PDF and the portal agree** for months covered by both (Apr 2024 – Jun 2025, plus several earlier ones)?
   Compare row counts and batch numbers (step 6).
3. ~~Where are the unlisted Aug–Dec 2024 PDFs linked from, if anywhere?~~ **Decided (Harith, 2026-11-05): skipped.**
   The portal JSON (primary, ADR 0004) already has those months' rows; the PDFs would only add extraction-benchmark
   months, and Apr 2024 – Jun 2025 already gives about 14 overlap months. No URL guessing.
4. What does the bulk "Samples declared NSQ 2017-2023" file contain?
5. Are the PDFs text-based or scanned images? (step 6)
6. ~~Scraping policy for guest tokens / request signing?~~ **Decided (ADR 0003):** anonymous-visitor rule.
   Jan Aushadhi guest token is allowed; NPPA request signing is not.
7. **"Typical branded price" (plan §4.6) has no clean bulk source.** Pharma Sahi Daam has branded MRPs but is signed.
   Partial public options: the TMR anti-cancer brand-MRP lists (2019; 2026 orders feed) and the new-drug retail-price orders.
8. ~~NPPA current ceiling prices?~~ **Decided (ADR 0003):** manual browser "Download CSV" from the 2026 Compendium
   dashboard, stored via the downloader's manual-drop path (file + who/when/where metadata).
9. **NPPA ceiling-price history has gaps:** compendia 2016/2022 and lists 2014/2018/2020, then orders from 2026 only.
   Orders from 2021–2025 aren't listed anywhere we found.
10. **Jan Aushadhi `mrp` = 0 for 353 products (14%)** (§3). Decide in Phase 3 how to treat them (proposed: missing).
11. **9 NPPA orders have no extractable text** (6 scanned, 3 text-as-graphics; §7.2), 4 of them with prices. OCR isn't
    in the stack. Decide in Phase 3/4 whether they matter once the 2026 Compendium CSV (manual drop) is in.

---

## 6. How downloads are stored in `raw/`

Built in Phase 1 step 4b (`ingestion/src/drugwatch_ingestion/store.py`). Every downloaded file is one
**item version**:

```
raw/<item prefix>/<sha256>.<ext>             the bytes exactly as downloaded (never decoded or edited)
raw/<item prefix>/<sha256>.<ext>.meta.json   metadata sidecar (JSON, UTF-8)
```

- **Item prefix:** one logical thing we download. Per source (set in step 4c):

  | Source | Prefix | One item = |
  |---|---|---|
  | CDSCO portal | `cdsco-portal/<nsq\|spurious>/<YYYY-MM>` | one month's table, all sources (`source=All`) |
  | Jan Aushadhi | `jan-aushadhi/products/<YYYY-MM>` (month collected) | one snapshot of the whole product list; skipped if this month's exists |
  | NPPA | `nppa/<compendium\|dpco2013\|category-lists>/<doc id>`, orders: `nppa/orders/<YYYY-MM>/<doc id>` | one listed PDF, or one NPPA data page stored as `.html` (doc id = NPPA's file/page name) |
  | Manual drop (any source) | `<source>/<dataset>/<period>`, e.g. `nppa/compendium-2026/2026-11` | one file a person downloaded in a browser (ADR 0003 §2) |
  | CDSCO PDFs | `cdsco-pdf/<central-nsq\|state-nsq\|spurious\|combined>/<YYYY-MM>/<file id>` (bulk file: `cdsco-pdf/nsq-bulk/2017-2023/<file id>`) | one listed PDF; the file id keeps an original and a "Revised" list apart |

- **Named by content hash:** the same bytes always get the same name, so they're stored once. If a source
  changes a file, the new version is stored next to the old one, never over it.
- **Sidecar = "done" marker:** written after the file. An item counts as stored only when a sidecar exists.
- **Sidecar fields:**
  - always: `source`, `method` (`auto` / `manual`, ADR 0003), `key`, `sha256`, `size_bytes`, `stored_at`;
  - plus what the source adapter adds: `alert_month` (CDSCO portal also: `dataset`, `row_count`, `encoding`;
    CDSCO PDFs also: `dataset`, `file_id`, the listing row's `title` / `release_date` / `size_text`, `first_hop_url`;
    Jan Aushadhi: `dataset`, `snapshot_month`, `row_count`, `active_count`, `request_body`; no `alert_month`;
    NPPA: `dataset` (section), `title`, `order_date` (orders only), `listing` URL and size text;
    manual drops: `dataset`, `period`, and `manual` = who / when (and whether "when" came from the file's
    modified time) / page URL / original file name / note, instead of `request`),
    and for automatic downloads the request details
    (URL with parameters, final URL, HTTP status, content type, ETag, Last-Modified, fetch time, User-Agent).
  - Request headers are never stored, because they can hold tokens.
- **Checking it:** `python -m drugwatch_ingestion.inventory` lists the bucket and confirms every file has its sidecar
  (and the reverse) and still matches its SHA-256. 2026-11-07: 321 files, 152.5 MB, no problems.

---

## 7. What's inside the files (step 6)

Surveyed 2026-11-07 from the copies in `raw/`, with **pdfplumber 0.11.10** run temporarily (`uv run --with`, not added
to the project: it becomes a project dependency in Phase 2). A page counts as **text** with ≥ 50 characters, **scanned**
with fewer characters and images covering over half the page, otherwise **blank**.

### 7.1 CDSCO PDFs (44 files, 251 pages)

**All 44 are real text, with no scanned pages** (one blank page, Mar 2025). Phase 2 needs no OCR for CDSCO.

**Six layout families** (Phase 2 needs one parser per family, not per month). Corrected 2026-11-08 by the Phase 2
classifier (`extraction/src/drugwatch_extraction/classify.py`), which checks every file's header cells: the first
version of this table said B had 30 files and lumped F into C.

| Family | Files | Months | Columns | Made with | Notes |
|---|---|---|---|---|---|
| A. Vaccine lists (central) | 11 | Jul 2017 – Apr 2023, scattered | 8: Vaccine Name, Batch No., Mfg Date, Expiry Date, Manufactured By, NSQ Result, Reported by CDSCO Laboratory | Excel 2016 | **1 page each, a few rows**; title and "A. Central Laboratories" rows above the header |
| B. NSQ lists (central + state) | 19 (10 central, 9 state) | Apr 2024 – Jun 2025 | 8: S.No, drug name, Batch No., Manufacturing Date, Expiry Date, Manufactured By, NSQ Result, Reported by CDSCO/State Laboratory | Word 2013–2019 | **Two names for the drug column:** "Name of Drugs/medical device/cosmetics" (2024) and "Product/Drug Name" (2025). Up to Feb 2025 a section row ("A. CDSCO/Central Laboratories", "B. State Laboratories") comes before the header |
| C. Spurious / combined lists | 10 (9 spurious, 1 combined) | Aug 2024 – Jun 2025 | 9–12: Name of Drugs/medical devices…, Batch No., Date of Manufacture, Date of Expiry, Manufactured By, Reason for failure, Drawn By, (From), Firm's reply, (Remarks) | Word 2013–2019 | Columns drift: "From" in Aug 2024, no "Remarks" in Sep 2024, merged name cells → 12 columns in Jun 2025 |
| D. Combined lists 2018 | 2 | May, Aug 2018 | 6: Sl. No., Name of Drugs/medical devices, Batch No./Date of Manufacture (**one cell**), Reason for failure, Drawn By, From | Word 2016 | full drug lists, 6–7 pages |
| E. Bulk vaccine file | 1 | 2017 – 2023 | 10, incl. regulatory action | Acrobat Pro 9 | 5 pages |
| F. Spurious list Apr 2024 | 1 | Apr 2024 | Product/Drug Name, B.No., Manufacturing Date, Expiry Date, Manufactured by as per label, Sales outlets involved in distribution, Response of original manufacturer, Reported by CDSCO/State/Manufacturer | Word 2016 | grouped by state ("NCT of DELHI" rows); no "Reason for failure" |

Things a parser must tolerate: header words broken across lines (`Manufactu ring Date`, `S.N o`), section rows inside
tables, merged cells, and column sets that change month to month.

**Key finding: the 2017–2023 "central NSQ" PDFs are vaccine-only lists** (Central Drugs Laboratory). Full drug NSQ lists
in PDF start only in **Apr 2024**. The portal includes vaccines too: batches `4121MC040` (Jun 2022) and `1641V`
(Apr 2019) from the vaccine PDFs appear in the portal for the same months. So the PDFs' **unique** history is pre-2019:
six vaccine lists (2017–2018), the two full drug lists of 2018 (family D) and the bulk vaccine file. **Phase 2's main
work and its accuracy benchmark are families B, C and F (2024–2025), with the portal as the answer key.**

### 7.2 NPPA PDFs (164 files, 1,209 pages, no read errors)

| Section | Files | Pages | Result |
|---|---|---|---|
| Compendium (2016, 2022) | 2 | 75 | all text (1 blank page) |
| DPCO 2013 lists (2018, 2020, TMR brands) | 3 | 47 | all text |
| Category lists | 5 | 36 | all text (2 blank pages) |
| Orders 2026 | 154 | 1,051 | **145 text, 6 scanned, 3 with no extractable text** (pages drawn as graphics) |

The 9 unreadable orders: 6 scanned one- or two-page letters (mostly circulars, but one is a ceiling-price fixation,
17 Apr 2026) and 3 from 1 Jun 2026 (retail prices for 30 new drugs, a ceiling-price revision, a Ringer Lactate
corrigendum). Open question 11. The four 2014 DPCO lists are HTML tables (§2), so they need no PDF parsing at all.

### 7.3 Structured sources

The CDSCO portal (§1b) and Jan Aushadhi (§3) are JSON with named fields. They need decoding and cleaning (Phase 3),
not extraction.
