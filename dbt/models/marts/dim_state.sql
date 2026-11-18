-- One row per Indian state and union territory, from the reviewed vocabulary seed.
--
-- Built from the seed rather than from the data, which matters: a state with no findings in the
-- archive still gets a row, so a map or a state filter shows "0 reports" instead of leaving the
-- state out entirely. Driving dimensions from a reference list rather than from observed values
-- is the normal way to avoid that kind of silent gap.
--
-- `alias_count` is how many spellings of this state the vocabulary recognises, which makes the
-- seed's coverage visible in the warehouse instead of only in the CSV.

with aliases as (

    select * from {{ ref('india_state_alias') }}

)

select
    md5(state_name) as state_id,  -- same formula dim_manufacturer uses, so the join lines up
    state_name,
    state_type,  -- State or Union Territory
    count(*) as alias_count
from aliases
group by state_name, state_type
