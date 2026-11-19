-- The reviewed lab-city seed must agree with CDSCO wherever CDSCO says both.
--
-- `seeds/lab_city_state.csv` says which state each laboratory's city is in. That is reviewed
-- knowledge rather than data, so it has to be checkable: some reporter strings name both the city
-- and the state ("DTL, Bengaluru, Karnataka"), and for those the seed must match what was
-- printed. 15 of the seed's 33 cities can be checked this way, and a disagreement means the seed
-- is wrong - the archive is not.
--
-- This is `analyses/lab_city_crosscheck.sql` promoted from "a query someone ran once" to a test
-- the build fails on, which is what step 4 is for.

with reporters as (

    select
        sample_id,
        ' ' || regexp_replace(
            lower(replace(coalesce(reported_by, ''), '.', '')), '[^a-z0-9&]+', ' ', 'g'
        ) || ' ' as reporter_norm
    from {{ ref('stg_nsq_sample') }}
    where reported_by is not null

),

stated as (

    select
        reporters.sample_id,
        reporters.reporter_norm,
        case when count(distinct alias.state_name) = 1 then min(alias.state_name) end as stated_state
    from reporters
    inner join {{ ref('india_state_alias') }} as alias
        on reporters.reporter_norm ~ ('\m' || alias.alias || '\M')
    group by reporters.sample_id, reporters.reporter_norm

)

select distinct
    city.city,
    city.state_name as seed_says,
    stated.stated_state as cdsco_printed
from stated
inner join {{ ref('lab_city_state') }} as city
    on stated.reporter_norm ~ ('\m' || city.city || '\M')
where stated.stated_state is not null
  and stated.stated_state <> city.state_name
