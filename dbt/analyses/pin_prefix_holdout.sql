-- Holdout check for the learned PIN-prefix -> state map (int_pin_prefix_state).
--
-- An "analysis" is SQL dbt compiles but never runs as a model: a query kept under version control
-- because the number it produces is a claim the project makes.
--
-- The claim: a state derived from a PIN prefix agrees with a state the address spells out about
-- 99.8% of the time. Checking the map against the rows it was learned from would be circular and
-- would report a meaningless 100%, so this learns from one arbitrary half of the known rows (split
-- on the id, which is an md5 and therefore unrelated to geography) and predicts the other half,
-- where the state is known independently.
--
-- Run it (from dbt/):
--     uv run --env-file ../.env dbt compile -s pin_prefix_holdout
--     docker compose exec -T postgres psql -U drugwatch \
--         -f /dev/stdin < target/compiled/drugwatch/analyses/pin_prefix_holdout.sql
--
-- Last run 2026-11-19: threshold 3 -> 461 predictions, 460 agreed, 1 wrong (99.78%);
-- threshold 2 -> 490 predictions, 2 wrong (99.59%). The single error is prefix 244, which covers
-- Moradabad (Uttar Pradesh) and Kashipur (Uttarakhand); the half it was learned from happened to
-- be unanimous. That is the shape of the residual risk: always between two neighbouring states.

with known as (

    select
        address.manufacturer_id,
        address.pin_code,
        named.state_from_name as state_name,
        -- an arbitrary, stable half: the id is an md5, so its last hex digit carries no geography
        right(address.manufacturer_id, 1) in ('0', '1', '2', '3', '4', '5', '6', '7') as learn_fold
    from {{ ref('int_manufacturer_address') }} as address
    inner join {{ ref('int_manufacturer_state') }} as named using (manufacturer_id)
    where address.pin_code is not null
      and named.name_match_status = 'matched'

),

learned as (

    select
        left(pin_code, 3) as pin_prefix,
        count(*) as observations,
        count(distinct state_name) as states_seen,
        min(state_name) as state_name
    from known
    where learn_fold
    group by left(pin_code, 3)

),

thresholds as (select 2 as min_observations union all select 3),

predictions as (

    select
        thresholds.min_observations,
        known.state_name as truth,
        learned.state_name as predicted
    from thresholds
    cross join known
    inner join learned on left(known.pin_code, 3) = learned.pin_prefix
    where not known.learn_fold
      and learned.states_seen = 1
      and learned.observations >= thresholds.min_observations

)

select
    min_observations,
    count(*) as held_out_predictions,
    count(*) filter (where truth = predicted) as agreed,
    count(*) filter (where truth <> predicted) as wrong,
    round(100.0 * count(*) filter (where truth = predicted) / count(*), 2) as pct_agreement
from predictions
group by min_observations
order by min_observations
