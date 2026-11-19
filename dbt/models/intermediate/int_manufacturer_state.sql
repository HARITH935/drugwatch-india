-- The state a manufacturer's address NAMES, matched against the reviewed vocabulary seed.
--
-- This is the first of two signals (the second is int_pin_prefix_state, which is learned from
-- this one's answers). It refuses to answer whenever the evidence is not clean - the same rule as
-- Phase 3's manufacturer merging: a missing state is better than a wrong one.
--
-- Three traps, each found by reading real addresses rather than by imagining what might go wrong:
--
--   1. **There is a village called Kerala - in Gujarat.** "Plot No. 401, GIDC Kerala, Bavla,
--      Dist. Ahmedabad, Gujarat" matches both Kerala and Gujarat. A row matching two different
--      states resolves to NULL, never to the first or the longest match. 5 companies sit there.
--
--   2. **A state name is often just a road name.** "P.O. Delhi Road, Fazilpur, Sonepat-131001" is
--      in Haryana, and "194, Mile Stone, Ambala-Delhi Highway" is in Haryana too. 10 addresses do
--      this, so a match immediately followed by road/highway/bypass/marg/NH is thrown away.
--      These two were not caught by the two-match rule, because the real state was never spelled
--      out - only the PIN gave it away. They were found by holding the PIN map out against this
--      model's answers and reading every disagreement.
--
--   3. **Marketer addresses**, handled upstream in int_manufacturer_address.
--
-- Matching uses Postgres' `\m...\M` word boundaries on the normalised copy, so "hp" cannot match
-- inside "HPSIDC", and the seed's aliases are stored already normalised, so there is no regex
-- escaping to get wrong.

-- A state name followed by any of these is part of a road's name, not a location.
{% set road_words = 'road|highway|hwy|bypass|byepass|expressway|marg|nh' %}

with addresses as (

    select * from {{ ref('int_manufacturer_address') }}

),

matches as (

    select
        addresses.manufacturer_id,
        alias.state_name,
        alias.alias
    from addresses
    inner join {{ ref('india_state_alias') }} as alias
        on addresses.own_address_norm ~ ('\m' || alias.alias || '\M')
        -- ...but not where it is only naming a road
        and addresses.own_address_norm !~ ('\m' || alias.alias || ' ({{ road_words }})\M')

),

decided as (

    select
        manufacturer_id,
        count(distinct state_name) as states_matched,
        min(state_name) as only_state_matched,
        string_agg(
            distinct alias || ' -> ' || state_name, '; ' order by alias || ' -> ' || state_name
        ) as match_evidence
    from matches
    group by manufacturer_id

)

select
    addresses.manufacturer_id,
    addresses.canonical_name,
    addresses.latest_address,
    addresses.pin_code,

    -- the answer, or null when the address does not say so cleanly
    case
        when decided.states_matched = 1 then decided.only_state_matched
    end as state_from_name,

    case
        when addresses.latest_address is null then 'no_address'
        when decided.manufacturer_id is null then 'no_state_in_address'
        when decided.states_matched = 1 then 'matched'
        else 'conflicting_states'  -- left unresolved on purpose: see the Kerala-in-Gujarat case
    end as name_match_status,

    decided.match_evidence,
    addresses.own_address_norm <> addresses.address_norm as address_had_marketer

from addresses
left join decided using (manufacturer_id)
