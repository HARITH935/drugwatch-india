-- One row: how often the laboratory that tested a batch is in a different state from its maker.
--
-- This is the single number that justifies the states dashboard existing in the shape it does, so
-- it is computed from the data rather than written into a dashboard's text. A figure typed into
-- prose is correct on the day it is written and silently wrong afterwards; this one is rebuilt by
-- every `dbt build`.
--
-- Why it matters (docs/analytics-findings.md §4): CDSCO's central laboratories draw samples
-- nationwide, so "reports by state" means two unrelated things. West Bengal tests 1,758 findings
-- and makes 103. Reading "tested here" as "unsafe medicine here" measures where the laboratories
-- are, not where the problems are.
--
-- Only findings where BOTH states are known can answer the question, and that denominator is
-- published as its own column: 5,391 of 7,126 findings, because 603 manufacturers have no
-- resolvable state and 191 findings name no reporting state.

with comparable as (

    select
        fact.reported_state_name as lab_state,
        manufacturers.state_name as maker_state
    from {{ ref('fact_nsq_sample') }} as fact
    inner join {{ ref('dim_manufacturer') }} as manufacturers using (manufacturer_id)
    where fact.reported_state_name is not null
      and manufacturers.state_name is not null

)

select
    count(*) as findings_with_both_states_known,
    count(*) filter (where lab_state <> maker_state) as tested_in_a_different_state,
    count(*) filter (where lab_state = maker_state) as tested_in_the_same_state,
    round(100.0 * count(*) filter (where lab_state <> maker_state) / count(*), 1)
        as pct_tested_in_a_different_state,
    -- the share of the whole archive this question can be asked of at all
    round(
        100.0 * count(*) / (select count(*) from {{ ref('fact_nsq_sample') }}), 1
    ) as pct_of_findings_comparable
from comparable
