-- Who reported each finding: a central or a state laboratory, and which state it sits in.
--
-- CDSCO prints one free-text field, `reported_by`: "CDL Kolkata", "RDTL, Guwahati",
-- "DTL, Bengaluru, Karnataka", "State Drugs Laboratory, Punjab", "Drugs Inspector, Bihar",
-- "King Institute of Preventive Medicine & Research, Guindy, Chennai-32". Two things are read
-- out of it, each from a reviewed seed, and each refusing to answer when the evidence is unclear.
--
-- **lab_type** (plan §8.1) comes from `lab_type_marker`. It matters because the two kinds of lab
-- are not comparable: CDSCO's own laboratories (CDL, CDTL, RDTL) test samples drawn nationwide,
-- while a state laboratory tests samples drawn in its own state. Counting them together and
-- calling the result "reports per state" would measure testing effort, not drug quality.
-- A central marker wins over a state marker, because the central phrases are the more specific:
-- "Central Drugs Testing Laboratory" contains "drugs testing laboratory".
--
-- **the lab's state** comes from the reporter naming it outright ("...Laboratory, Punjab"),
-- else from the city (`lab_city_state`). Only ~32% of rows name a state, but nearly all name a
-- city, and the cities are a closed set of about twenty: the laboratories CDSCO actually uses.
-- 9 of those cities also appear in strings that spell their state out, so the seed is not taken
-- on trust - `analyses/lab_city_crosscheck.sql` checks it against them.
--
-- This state is the REPORTING lab's state, which is not where the medicine was made. A central
-- lab in Kolkata tests batches from everywhere, so "West Bengal" here says nothing about the
-- manufacturer. dim_manufacturer.state_name is the manufacturing state; the two must never be
-- added together or shown as one map.

with reporters as (

    select
        sample_id,
        reported_by,
        ' ' || regexp_replace(
            lower(replace(coalesce(reported_by, ''), '.', '')), '[^a-z0-9&]+', ' ', 'g'
        ) || ' ' as reporter_norm
    from {{ ref('stg_nsq_sample') }}

),

type_matches as (

    select
        reporters.sample_id,
        marker.lab_type,
        marker.marker
    from reporters
    inner join {{ ref('lab_type_marker') }} as marker
        on reporters.reporter_norm ~ ('\m' || marker.marker || '\M')

),

lab_type as (

    select
        sample_id,
        -- central first: see the precedence note above
        case
            when bool_or(lab_type = 'Central') then 'Central'
            when bool_or(lab_type = 'State') then 'State'
        end as lab_type,
        bool_or(lab_type = 'Central') and bool_or(lab_type = 'State') as had_both_kinds,
        string_agg(distinct marker, '; ' order by marker) as lab_type_evidence
    from type_matches
    group by sample_id

),

state_named as (

    select
        reporters.sample_id,
        -- unanimous only, exactly as the address matcher does it
        case
            when count(distinct alias.state_name) = 1 then min(alias.state_name)
        end as state_name
    from reporters
    inner join {{ ref('india_state_alias') }} as alias
        on reporters.reporter_norm ~ ('\m' || alias.alias || '\M')
    group by reporters.sample_id

),

state_from_city as (

    select
        reporters.sample_id,
        case
            when count(distinct city.state_name) = 1 then min(city.state_name)
        end as state_name,
        string_agg(distinct city.city, '; ' order by city.city) as city_evidence
    from reporters
    inner join {{ ref('lab_city_state') }} as city
        on reporters.reporter_norm ~ ('\m' || city.city || '\M')
    group by reporters.sample_id

)

select
    reporters.sample_id,
    reporters.reported_by,

    lab_type.lab_type,
    lab_type.lab_type_evidence,
    lab_type.had_both_kinds as lab_type_had_both_kinds,

    coalesce(state_named.state_name, state_from_city.state_name) as reported_state_name,
    case
        when state_named.state_name is not null then 'reporter_names_the_state'
        when state_from_city.state_name is not null then 'lab_city'
    end as reported_state_source,
    state_from_city.city_evidence as lab_city_evidence

from reporters
left join lab_type using (sample_id)
left join state_named using (sample_id)
left join state_from_city using (sample_id)
