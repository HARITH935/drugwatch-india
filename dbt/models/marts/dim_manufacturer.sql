-- One row per manufacturer: Phase 3's resolved company, plus where it is.
--
-- The state comes from two signals, in this order:
--
--   1. **the address names it** (int_manufacturer_state) - a reviewed vocabulary of 62 spellings
--      of the 36 states and UTs, refusing to answer when two states match;
--   2. **the postal code**, through a prefix map LEARNED from the addresses that do name their
--      state (int_pin_prefix_state), used only where the first signal gave nothing.
--
-- `state_name_source` says which one answered, so every row can be judged on its own evidence -
-- a PIN-derived state is good to ~99.8% by holdout, a named one is as good as the address.
-- Null still means "not stated, and not guessed", never "no state".
--
-- `city` from plan Section 8.1 is still absent. A city has no closed vocabulary to check against
-- the way 36 states do, and the same learned trick does not transfer: a 3-digit PIN prefix covers
-- a whole postal district, not a town.

with manufacturers as (

    select * from {{ ref('int_manufacturer_address') }}

),

named as (

    select * from {{ ref('int_manufacturer_state') }}

),

from_pin as (

    select
        manufacturers.manufacturer_id,
        prefix_map.state_name,
        prefix_map.observations
    from manufacturers
    inner join {{ ref('int_pin_prefix_state') }} as prefix_map
        on left(manufacturers.pin_code, 3) = prefix_map.pin_prefix

),

combined as (

    select
        manufacturers.manufacturer_id,
        manufacturers.canonical_name,
        manufacturers.name_variants,
        manufacturers.name_variant_count,

        coalesce(named.state_from_name, from_pin.state_name) as state_name,

        case
            when named.state_from_name is not null then 'address_names_the_state'
            when from_pin.state_name is not null then 'learned_pin_prefix'
        end as state_name_source,

        named.name_match_status,
        named.match_evidence as state_match_evidence,
        manufacturers.pin_code,
        from_pin.observations as pin_prefix_observations,

        manufacturers.latest_address,
        manufacturers.first_alert_month,
        manufacturers.last_alert_month

    from manufacturers
    left join named using (manufacturer_id)
    left join from_pin using (manufacturer_id)

)

select
    *,
    case when state_name is not null then md5(state_name) end as state_id
from combined
