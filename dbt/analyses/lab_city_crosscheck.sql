-- Cross-check for the reviewed lab-city seed (seeds/lab_city_state.csv).
--
-- The seed says which state each laboratory's city is in. That is reviewed knowledge, so the
-- archive is used to check it rather than to trust it: some reporter strings name both the city
-- and the state ("DTL, Bengaluru, Karnataka", "LUCKNOW, Uttar Pradesh"), and for those the seed
-- must agree with what CDSCO printed. A disagreement means the seed is wrong - not the data.
--
-- Run it (from dbt/):
--     uv run --env-file ../.env dbt compile -s lab_city_crosscheck
--     docker compose exec -T postgres psql -U drugwatch \
--         -f /dev/stdin < target/compiled/drugwatch/analyses/lab_city_crosscheck.sql
--
-- Last run 2026-11-19: 9 cities checkable, 0 disagreements. The other seeded cities are ones the
-- archive never spells a state out for (Mumbai, Chennai, Jaipur, Hyderabad, Indore...), which is
-- why they are in a reviewed seed in the first place; `verified_against_data` in the CSV records
-- which is which. Phase 4 step 4 turns this into a dbt test that fails the build.

with reporters as (

    select
        sample_id,
        ' ' || regexp_replace(
            lower(replace(coalesce(reported_by, ''), '.', '')), '[^a-z0-9&]+', ' ', 'g'
        ) || ' ' as reporter_norm
    from {{ ref('stg_nsq_sample') }}
    where reported_by is not null

),

-- what the reporter string itself says, where it says one state unambiguously
stated as (

    select
        reporters.sample_id,
        reporters.reporter_norm,
        case when count(distinct alias.state_name) = 1 then min(alias.state_name) end as stated_state
    from reporters
    inner join {{ ref('india_state_alias') }} as alias
        on reporters.reporter_norm ~ ('\m' || alias.alias || '\M')
    group by reporters.sample_id, reporters.reporter_norm

),

-- what the seed would say for the city in the same string
checked as (

    select
        stated.sample_id,
        stated.stated_state,
        city.city,
        city.state_name as seed_state
    from stated
    inner join {{ ref('lab_city_state') }} as city
        on stated.reporter_norm ~ ('\m' || city.city || '\M')
    where stated.stated_state is not null

)

select
    city,
    seed_state,
    stated_state,
    count(*) as rows,
    case when seed_state = stated_state then 'agrees' else 'DISAGREES - fix the seed' end as verdict
from checked
group by city, seed_state, stated_state
order by verdict desc, rows desc
