-- The centre of the star: one row per CDSCO finding, pointing at the dimensions.
--
-- Grain: one failed (or spurious) batch report, exactly as Phase 3 de-duplicated it (ADR 0010).
-- 7,126 rows, and `sample_id` carries straight through from staging so a row in gold can always
-- be traced back to its source document.
--
-- Two rules this model enforces, both from CLAUDE.md Section 6:
--
--   1. **A spurious report is never attributed to a manufacturer.** The name on a counterfeit
--      pack is the copied brand, so `manufacturer_id` is null on those 77 rows and the printed
--      name is kept apart in `name_on_pack`. Nothing downstream can count it against the real
--      company, because there is no key to count it under.
--   2. **Every row keeps its provenance.** source file, page, row index and the URL of the
--      original CDSCO document travel with the finding into gold, so every public view can show
--      the batch, the alert month and a link to the document it came from.
--
-- `reported_state_id` is the REPORTING LABORATORY's state, never the manufacturer's: a central
-- lab in Kolkata tests batches from everywhere. dim_manufacturer.state_name is the
-- manufacturing state. The two must never be shown as one map.
--
-- A left join to the dimensions, never an inner one: 128 rows have no manufacturer printed
-- (77 spurious + 51 where CDSCO simply did not name one). An inner join would silently drop
-- them, which would quietly under-report the archive.

with samples as (

    select * from {{ ref('stg_nsq_sample') }}

),

reporting_lab as (

    select * from {{ ref('int_reporting_lab') }}

)

select
    -- keys
    samples.sample_id,
    md5(samples.product_name) as drug_id,
    case
        when samples.manufacturer_canonical is not null
            then md5(samples.manufacturer_canonical)
    end as manufacturer_id,
    to_char(samples.alert_month_start, 'YYYYMMDD')::int as alert_date_id,

    -- what was found
    samples.batch_no,
    samples.batch_no_raw,
    samples.mfg_date,
    samples.expiry_date,
    samples.dates_valid,
    samples.failure_reason,
    samples.failure_categories,
    samples.is_spurious,
    samples.name_on_pack,  -- only ever filled when is_spurious
    samples.reported_by,   -- the lab or authority that reported it, as printed

    -- Who tested it. Central (CDSCO's own CDL/CDTL/RDTL) and state laboratories are NOT
    -- comparable: a central lab tests samples drawn nationwide, a state lab tests its own
    -- state's. Counting them together as "reports per state" would measure testing effort, not
    -- drug quality - so the type travels with the row.
    reporting_lab.lab_type,
    reporting_lab.reported_state_name,
    case
        when reporting_lab.reported_state_name is not null
            then md5(reporting_lab.reported_state_name)
    end as reported_state_id,  -- FK to dim_state: the REPORTING LAB's state, not the maker's
    reporting_lab.reported_state_source,
    samples.remarks,
    samples.firm_reply,

    -- when
    samples.alert_month,
    samples.alert_month_start,

    -- provenance: never dropped, at any layer (CLAUDE.md Section 5)
    samples.source_dataset,
    samples.source_key as source_file,
    samples.source_sha256,
    samples.source_url,
    samples.page as source_page,
    samples.row_index as source_row_index,
    samples.extraction_method,
    samples.also_reported_in

from samples
left join reporting_lab using (sample_id)
