-- One row per spurious (counterfeit) finding, with the detail a person needs to check a pack.
--
-- **This is the most easily misread table in the warehouse, so it is built to be hard to misuse.**
--
-- A spurious finding means CDSCO judged the pack itself to be fake. The company name printed on it
-- is the brand somebody *copied* - that company is the victim of the counterfeit, not its maker
-- (CLAUDE.md §6). Phase 3 therefore records that name in `name_on_pack` and leaves the
-- manufacturer null, and this mart:
--
--   - carries **no `manufacturer_id` at all**, so no join can attach these findings to a company;
--   - names the column `name_printed_on_the_pack` rather than anything resembling "manufacturer",
--     because a column called `company` would eventually be charted as one;
--   - keeps the batch number, the alert month and the CDSCO link on every row, which is what makes
--     a finding checkable rather than just alarming.
--
-- Scale, stated so no one over-reads it: 77 findings, first seen 2024-04. Spurious reporting is a
-- recent and small part of the archive - it is not a measure of how much counterfeiting exists,
-- only of what CDSCO published.

select
    fact.sample_id,
    fact.alert_month,
    fact.alert_month_start,

    -- what was found
    fact.batch_no,
    drug.product_name,
    drug.dosage_form,

    -- The copied brand. NOT the maker: nothing here identifies who produced the fake.
    fact.name_on_pack as name_printed_on_the_pack,
    fact.failure_reason,
    fact.failure_categories,

    -- who reported it, and the document that says so
    fact.reported_by,
    fact.lab_type,
    fact.reported_state_name,
    fact.source_url,
    fact.source_dataset

from {{ ref('fact_nsq_sample') }} as fact
inner join {{ ref('dim_drug') }} as drug using (drug_id)
where fact.is_spurious
