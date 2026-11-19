-- Reports per state, counted two ways that must never be confused.
--
-- Plan §8.2: "reports by manufacturing and reporting state". Those are two different numbers and
-- this mart keeps them in separate columns, side by side, with dim_state as the spine so a state
-- with nothing in either column still has a row (a map with a missing state looks like a missing
-- state, not like zero).
--
--   `reports_made_here`   - findings whose MANUFACTURER is in this state.
--   `reports_tested_here` - findings whose REPORTING LABORATORY is in this state.
--
-- They are not comparable, and the data shows why: CDSCO's central laboratories test samples
-- drawn nationwide, so 498 findings tested in West Bengal were made in Himachal Pradesh. Reading
-- `reports_tested_here` as "unsafe medicine in this state" would be measuring where the
-- laboratories are. `state_lab_reports_tested_here` is the honest subset for that question -
-- a state laboratory tests its own state's samples - and it is given separately for exactly
-- that reason.

with findings as (

    select
        fact.sample_id,
        fact.manufacturer_id,
        fact.reported_state_name,
        fact.lab_type,
        fact.alert_month,
        manufacturers.state_name as manufacturing_state
    from {{ ref('fact_nsq_sample') }} as fact
    left join {{ ref('dim_manufacturer') }} as manufacturers using (manufacturer_id)

),

made_here as (

    select
        manufacturing_state as state_name,
        count(*) as reports_made_here,
        count(distinct manufacturer_id) as manufacturers_here,
        max(alert_month) as last_alert_month_made_here
    from findings
    where manufacturing_state is not null
    group by manufacturing_state

),

tested_here as (

    select
        reported_state_name as state_name,
        count(*) as reports_tested_here,
        count(*) filter (where lab_type = 'State') as state_lab_reports_tested_here,
        count(*) filter (where lab_type = 'Central') as central_lab_reports_tested_here
    from findings
    where reported_state_name is not null
    group by reported_state_name

)

select
    states.state_id,
    states.state_name,
    states.state_type,
    coalesce(made_here.reports_made_here, 0) as reports_made_here,
    coalesce(made_here.manufacturers_here, 0) as manufacturers_here,
    made_here.last_alert_month_made_here,
    coalesce(tested_here.reports_tested_here, 0) as reports_tested_here,
    coalesce(tested_here.state_lab_reports_tested_here, 0) as state_lab_reports_tested_here,
    coalesce(tested_here.central_lab_reports_tested_here, 0) as central_lab_reports_tested_here

from {{ ref('dim_state') }} as states
left join made_here using (state_name)
left join tested_here using (state_name)
