-- Manufacturers reported in three or more separate CDSCO alert months.
--
-- Plan §8.2 calls this mart `mart_repeat_offenders`. **Renamed deliberately.** CLAUDE.md
-- Section 6 is explicit: an NSQ finding applies to one batch, sampling is not random, and no
-- manufacturer may be called fraudulent. "Offender" is a verdict; what this table actually holds
-- is a count of alert months in which a company was reported. The column names say the same
-- thing: `alert_months_reported`, not `violations`.
--
-- Why alert MONTHS rather than reports: ten findings in one alert is one event - a single
-- inspection sweep of one factory - while one finding in each of ten months is a pattern that
-- persisted. Counting months is the conservative reading of a non-random sample.
--
-- SQL techniques the plan asks for here: DENSE_RANK to rank companies without gaps when several
-- tie, and LAG to measure the gap between consecutive alert months.

with reported_months as (

    -- one row per manufacturer per alert month they appear in (so the LAG below steps from one
    -- alert month to the next, never month by calendar month)
    select
        manufacturer_id,
        alert_month_start,
        count(*) as reports_in_month
    from {{ ref('fact_nsq_sample') }}
    where manufacturer_id is not null
    group by manufacturer_id, alert_month_start

),

gaps as (

    select
        manufacturer_id,
        alert_month_start,
        reports_in_month,
        lag(alert_month_start) over (
            partition by manufacturer_id order by alert_month_start
        ) as previous_alert_month
    from reported_months

),

per_manufacturer as (

    select
        manufacturer_id,
        count(*) as alert_months_reported,
        sum(reports_in_month) as reports_total,
        min(alert_month_start) as first_alert_month,
        max(alert_month_start) as last_alert_month,
        -- the longest quiet stretch between two alerts, in months
        max(
            case
                when previous_alert_month is not null then (
                    extract(year from alert_month_start) * 12 + extract(month from alert_month_start)
                    - extract(year from previous_alert_month) * 12
                    - extract(month from previous_alert_month)
                )
            end
        )::int as longest_gap_months
    from gaps
    group by manufacturer_id

)

select
    per_manufacturer.manufacturer_id,
    manufacturers.canonical_name,
    manufacturers.state_name,
    per_manufacturer.alert_months_reported,
    per_manufacturer.reports_total,
    per_manufacturer.first_alert_month,
    per_manufacturer.last_alert_month,
    per_manufacturer.longest_gap_months,
    -- DENSE_RANK, not ROW_NUMBER: companies on the same number of alert months share a rank,
    -- and the next rank is not skipped. A public list must not imply an order that the data
    -- does not support.
    dense_rank() over (order by per_manufacturer.alert_months_reported desc) as rank_by_alert_months,
    dense_rank() over (order by per_manufacturer.reports_total desc) as rank_by_reports

from per_manufacturer
inner join {{ ref('dim_manufacturer') }} as manufacturers using (manufacturer_id)
where per_manufacturer.alert_months_reported >= 3
