# ADR 0003 — Data access and republishing policy

- **Status:** Accepted
- **Date:** 2026-11-04
- **Decided by:** Harith (project owner)
- **Details:** `docs/data-sources.md` §4 (robots.txt and terms, with quotes)

---

## Context

Phase 1 steps 1–3 surveyed six hosts run by three owners: CDSCO (`cdsco.gov.in`, `cdscoonline.gov.in`),
NPPA (`nppa.gov.in`, `nppaipdms.gov.in`) and PMBI / Jan Aushadhi (`janaushadhi.gov.in`, `pmbi.co.in`).

- **robots.txt:** none of the six publishes one (NPPA's returns 403, so it can't be read).
- **Terms of use:** none restricts automated access. They control **republishing**:
  - CDSCO: content "may not be reproduced partially or fully, without due permission".
  - PMBI / Jan Aushadhi: may be reproduced "after taking proper permission by sending a mail to us"; linking needs prior permission.
  - NPPA: may be reproduced "without requiring specific permission", with the source "prominently acknowledged".
  - All three: no framing of their pages; accurate reproduction only; nothing misleading or derogatory.
- **Two sites do more than plain HTTP:**
  - Jan Aushadhi's product API needs a **guest token** that the site issues to every anonymous visitor
    (`GET :8443/auth/generateGuestToken`). No login or secret is involved.
  - NPPA's IPDMS apps (Pharma Sahi Daam, the 2026 Compendium dashboard) pass data requests through
    `createFHashAjaxQuery()`, commented in their code as a *"security feature added on 28/07/2017"*. Direct calls fail.

We needed one rule for what the downloader may do, and one for what the live site may publish.

## Options considered

| Option | What gets automated | Trade-off |
|---|---|---|
| **A. Anonymous-visitor rule** | Anything a logged-out browser does on its own for every visitor, including guest tokens | Automates the Jan Aushadhi list. Easy to explain: "we do what any visitor's browser does, nothing more." |
| B. Plain files only | Only pages, files and JSON that need no token | Strictest, but the Jan Aushadhi list becomes a monthly manual chore. |
| C. Do whatever the page does | Everything, including copying NPPA's request signing | Rejected outright: it gets around a control the owner added on purpose. |

## Decision

**Option A**, plus a permission-first rule for republishing.

**1. Access rule.** The downloader may automatically fetch:
- public pages, files and JSON endpoints that a logged-out browser loads;
- short-lived guest tokens that a site issues to **every** anonymous visitor.

It must never:
- copy request-signing or anti-automation code (e.g. NPPA's `createFHashAjaxQuery`);
- call admin or login-protected endpoints (e.g. Jan Aushadhi `/api/v1/admin/...`), log in, or solve CAPTCHAs;
- disguise itself as a browser to get past a block. A 403 or 429 means stop and back off, not retry harder.

**2. Manual drop.** Where the rule blocks automation, Harith downloads the file in a normal browser. It is
stored in `raw/` with metadata: who downloaded it, when, the page URL it came from, and `method = manual`.

**3. Etiquette** (CLAUDE.md §7, made concrete):
- at least 3 seconds between requests to the same host;
- retries with exponential backoff, and a cap;
- an honest User-Agent naming the project and its public repo, e.g.
  `DrugWatchIndia/0.1 (+https://github.com/HARITH935/drugwatch-india)`, with no personal email;
- hash check against RustFS before downloading anything again.

**4. Republishing rule.**
- **CDSCO and Jan Aushadhi data** is not published on the live site until written permission arrives,
  tracked in `docs/permissions.md`. Requests go out now, not at launch.
- **NPPA data** may be published with prominent attribution.
- **For every source:** reproduce accurately, attribute it on every view, link to sources in a new tab and
  never in an iframe, and say that prices are "for information only, not a statement of law".

## Consequences

- **Jan Aushadhi product list:** automated monthly (guest token, then one `getAllProductForWeb` call).
- **NPPA current ceiling prices:** manual drop of the "Download CSV" from the 2026 Compendium dashboard.
  The older PDFs (compendia 2016/2022, lists 2014/2018/2020, the 2026 orders feed) are fetched automatically.
- **Pharma Sahi Daam is not used**, so plan §4.6's "typical branded price" has **no bulk source**.
  To revisit when price data is modelled (Phase 3/4). Partial public options are listed in `docs/data-sources.md` §5.
- **The downloader (step 4) needs two paths:** automatic fetch and manual drop.
- **Launch dependency:** Phase 12 can't publish CDSCO or Jan Aushadhi data without permission. If a request is
  refused or unanswered, we decide the fallback then, with a new ADR.
- **Phase 11:** source links open in a new tab; nothing from these sites is shown in an iframe.
- **Interview angle:** "Before writing the scraper I read every source's robots.txt and terms. The terms didn't
  limit fetching but did limit republishing, so I asked for permission early. I set a written rule for what
  the scraper may do: only what an anonymous visitor's browser does, never getting around a control the
  owner added on purpose."

## References

- CDSCO copyright policy: https://cdsco.gov.in/opencms/opencms//en/Copyright-Policy/
- CDSCO terms / disclaimer: https://cdsco.gov.in/opencms/opencms/en/terms_conditions/, https://cdsco.gov.in/opencms/opencms/en/disclaimer/
- NPPA copyright / hyperlink policy: https://nppa.gov.in/en/copyrightpolicy, https://nppa.gov.in/en/hyperlinkingpolicy
- Jan Aushadhi policies: Copyright / Hyperlink / Disclaimer sections of https://janaushadhi.gov.in
