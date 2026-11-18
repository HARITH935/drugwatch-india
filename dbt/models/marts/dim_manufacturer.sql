-- One row per manufacturer: Phase 3's resolved company, plus the state read out of its address.
--
-- The two halves are built separately on purpose - int_manufacturer aggregates the spellings,
-- int_manufacturer_state reads the address - so that neither depends on the other and each can
-- be checked on its own.
--
-- `state_name` is null wherever the address did not say so cleanly; `state_match_status` says
-- which it was (no address at all, no state in the address, or two states matched and the row was
-- left unresolved). Null here never means "no state" - it means "not stated, and not guessed".
--
-- `city` from plan Section 8.1 is still missing: a city has no closed vocabulary to check against
-- the way the 36 states and UTs do, so it needs its own piece and its own evidence.

with manufacturers as (

    select * from {{ ref('int_manufacturer') }}

),

located as (

    select * from {{ ref('int_manufacturer_state') }}

)

select
    manufacturers.manufacturer_id,
    manufacturers.canonical_name,
    manufacturers.name_variants,
    manufacturers.name_variant_count,

    -- where it is, as far as the address can be trusted
    located.state_name,
    case when located.state_name is not null then md5(located.state_name) end as state_id,
    located.state_match_status,
    located.match_evidence as state_match_evidence,

    manufacturers.latest_address,
    manufacturers.first_alert_month,
    manufacturers.last_alert_month

from manufacturers
left join located using (manufacturer_id)
