-- One row per CDSCO finding, as silver has it, with the two things the gold layer needs added:
-- a stable key and a real date for the alert month.
--
-- A staging model is deliberately thin: no joins, no filtering, no business rules. It is the
-- single place every downstream model reads the source through, so if silver's shape changes,
-- exactly one file changes with it.
--
-- There is little renaming to do here, and none is invented: Phase 3 already chose these column
-- names. Listing them out one by one is still worth it - it makes this file the contract. A new
-- column in silver cannot appear downstream by accident, and a deleted one fails here, loudly,
-- instead of somewhere deeper in the graph.

with silver as (

    select * from {{ source('silver', 'silver_nsq') }}

),

final as (

    select
        -- A surrogate key: one short stable id per finding, for the fact table to be keyed on
        -- and for dimensions to point at. Built from the provenance triple, which is unique
        -- across all 7,126 rows (verified) and - unlike a row number - does not change when the
        -- table is rebuilt or when CDSCO publishes a new month.
        -- `coalesce(page::text, '')` because portal rows have no page; without it, md5(null)
        -- is null and every portal row would get a null key.
        md5(
            source_key || '|' || coalesce(page::text, '') || '|' || row_index::text
        ) as sample_id,

        -- provenance: which document this came from (CLAUDE.md Section 6 requires every view to
        -- be able to link back to the original CDSCO document)
        source_dataset,
        source_key,
        source_sha256,
        source_url,
        page,
        row_index,
        extraction_method,
        also_reported_in,

        -- when CDSCO published the alert. `alert_month` stays text because that is what it is -
        -- 'YYYY-MM' names an alert, not a day. `alert_month_start` is the same month as a real
        -- date, so charts can sort and bucket by time and the fact can join to dim_date.
        alert_month,
        to_date(alert_month || '-01', 'YYYY-MM-DD') as alert_month_start,

        -- the batch this alert is about: normalised, and exactly as printed
        batch_no,
        batch_no_raw,

        -- dates, parsed and as printed. `dates_valid` is nullable on purpose: unknown is not
        -- the same as invalid.
        mfg_date,
        expiry_date,
        mfg_date_raw,
        expiry_date_raw,
        dates_valid,

        -- the medicine. product_name is the name as the document printed it; generic_name and
        -- brand_name are filled only where the split was unambiguous (~20% of rows).
        product_name_raw as product_name,
        generic_name,
        brand_name,
        dosage_form,
        strengths,

        -- who made it - or, for a spurious report, the name printed on the fake pack. Keeping
        -- those two apart is an ethics requirement, not a nicety (CLAUDE.md Section 6):
        -- a spurious finding must never be counted against the company whose name was copied.
        manufacturer_raw,
        manufacturer_name,
        manufacturer_address,
        manufacturer_canonical,
        is_spurious,
        name_on_pack,

        -- what was wrong: the lab's own words, plus the standard categories (ADR 0009)
        failure_reason,
        failure_categories,
        reported_by,
        remarks,
        firm_reply,

        -- when the loader last refreshed this row
        loaded_at

    from silver

)

select * from final
