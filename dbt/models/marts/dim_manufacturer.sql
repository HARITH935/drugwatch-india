-- One row per manufacturer, after Phase 3's entity resolution.
--
-- "Manufacturer" here means the canonical name a person either accepted or that RapidFuzz merged
-- at 98+ (Phase 3 step 5): 3,302 cleaned spellings collapsed into 2,609 companies. `name_variants`
-- keeps every spelling that maps to this row, so a user searching the name printed on their strip
-- still finds the company, and so an analyst can see exactly what was merged.
--
-- Deliberately NOT in this table:
--   - any count of findings. A dimension describes a thing; counting belongs in the marts, which
--     can then change their definitions without rebuilding this.
--   - rows for spurious reports. The name on a spurious pack is the copied brand, not the maker
--     (CLAUDE.md Section 6), and silver already leaves `manufacturer_canonical` null on those 77
--     rows. Filtering on null here is what keeps a faked name out of the manufacturer list.
--   - `state` and `city` from Section 8.1: the address is still one unparsed string. Those arrive
--     with dim_state, in the next piece of this step, rather than being guessed at now.

with samples as (

    select * from {{ ref('stg_nsq_sample') }}
    where manufacturer_canonical is not null

),

final as (

    select
        -- A surrogate key from the canonical name: stable as long as the name is, and it changes
        -- (correctly) if a later review merges this company into another one.
        md5(manufacturer_canonical) as manufacturer_id,
        manufacturer_canonical as canonical_name,

        -- every cleaned spelling that resolved to this company, and how many there were.
        -- 484 of the 2,609 companies have more than one.
        array_agg(distinct manufacturer_name order by manufacturer_name) as name_variants,
        count(distinct manufacturer_name) as name_variant_count,

        -- the address exactly as printed on the most recent alert, kept so the next piece has
        -- something to parse a state out of, and so a user can see what CDSCO actually printed
        (array_agg(manufacturer_address order by alert_month_start desc nulls last))[1]
            as latest_address,

        min(alert_month) as first_alert_month,
        max(alert_month) as last_alert_month

    from samples
    group by manufacturer_canonical

)

select * from final
