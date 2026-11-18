-- Which state each manufacturer is in, read out of the address CDSCO printed.
--
-- There is no state field in the archive: there is one address string per manufacturer, written
-- by whoever typed the alert. So this matches a reviewed vocabulary of state names, spelling
-- variants and abbreviations (`seeds/india_state_alias.csv`) against the address, and refuses to
-- answer when the evidence is not clean. Same rule as Phase 3's manufacturer merging: a missing
-- state is better than a wrong one.
--
-- Three things were found by reading real addresses first, and each one shaped the SQL below:
--
--   1. **There is a village called Kerala - in Gujarat.** "Plot No. 401, GIDC Kerala, Bavla,
--      Dist. Ahmedabad, Gujarat" matches both Kerala and Gujarat. So a row matching two different
--      states resolves to NULL, never to "the first one" or "the longest match".
--   2. **Road names carry state names.** "14/4, Delhi-Mathura Road, Faridabad, Haryana" is in
--      Haryana, not Delhi. Caught by the same two-match rule.
--   3. **Some addresses contain a SECOND company's address**, after "Marketed By" or "Mrkt:" -
--      the marketer, who is often in another state entirely (46 addresses). Everything from that
--      marker on is cut off before matching, because the manufacturer's state is the one printed
--      first. The markers are the ones that actually occur in the data, counted as whole words,
--      not imagined: mrkt (30), marketed (7), mrk (6), mkt (2), markt (1).
--      **"market" is deliberately NOT a marker**, though it occurs 4 times: it is part of real
--      addresses like "Vasavi Pharma Market Complex, Gollapudi". Matching a prefix instead of
--      whole words would have truncated those addresses and lost their state.
--
-- Matching is done on a normalised copy: lower-cased, dots removed ("H.P." -> "hp", "(M.P)" ->
-- "mp"), every other punctuation mark turned into a space, and '&' kept so "J&K" survives. The
-- aliases in the seed are stored already normalised, so there is no escaping to get wrong, and
-- `\m...\M` word boundaries stop "hp" from matching inside "HPSIDC".

with manufacturers as (

    select
        manufacturer_id,
        canonical_name,
        latest_address
    from {{ ref('int_manufacturer') }}

),

normalised as (

    select
        manufacturer_id,
        canonical_name,
        latest_address,
        -- leading and trailing spaces so a state name at either end still has a word boundary
        ' ' || regexp_replace(
            lower(replace(coalesce(latest_address, ''), '.', '')), '[^a-z0-9&]+', ' ', 'g'
        ) || ' ' as address_norm
    from manufacturers

),

cut as (

    select
        manufacturer_id,
        canonical_name,
        latest_address,
        address_norm,
        -- Cut everything from the first marketer marker onwards. One regexp over a list of whole
        -- words, so "market" inside a real address is left alone while "mrkt"/"mrk"/"mkt" are not.
        regexp_replace(
            address_norm, '\m(mrkt|mrk|marketed|markt|mktd|mkt)\M.*', ''
        ) as own_address_norm
    from normalised

),

matches as (

    select
        cut.manufacturer_id,
        alias.state_name,
        alias.alias,
        alias.alias_kind
    from cut
    inner join {{ ref('india_state_alias') }} as alias
        -- \m / \M are Postgres' word-boundary markers: "hp" matches " hp " and "(hp)", never
        -- the "hp" inside "hpsidc"
        on cut.own_address_norm ~ ('\m' || alias.alias || '\M')

),

decided as (

    select
        manufacturer_id,
        count(distinct state_name) as states_matched,
        min(state_name) as only_state_matched,
        string_agg(distinct alias || ' -> ' || state_name, '; ' order by alias || ' -> ' || state_name)
            as match_evidence
    from matches
    group by manufacturer_id

)

select
    cut.manufacturer_id,
    cut.canonical_name,
    cut.latest_address,
    -- the answer, or null when the evidence is not clean
    case when decided.states_matched = 1 then decided.only_state_matched end as state_name,
    case
        when cut.latest_address is null then 'no_address'
        when decided.manufacturer_id is null then 'no_state_in_address'
        when decided.states_matched = 1 then 'matched'
        else 'conflicting_states'  -- deliberately unresolved: see the Kerala-in-Gujarat case above
    end as state_match_status,
    -- kept so any answer can be audited back to the words that produced it
    decided.match_evidence,
    cut.own_address_norm <> cut.address_norm as address_had_marketer

from cut
left join decided using (manufacturer_id)
