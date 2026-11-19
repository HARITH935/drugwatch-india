-- NSQ reports per manufacturer per month, with rolling 6- and 12-month counts.
--
-- Plan §8.2's first mart, and the one the public manufacturer page is built on. Neutral by
-- construction (CLAUDE.md Section 6): every column counts *reports*, which is reporting history,
-- never a judgement about a company.
--
-- **The windows are RANGE windows over dates, not ROWS windows over rows**, and that is the one
-- thing worth looking at twice here. CDSCO does not publish every month - the archive jumps from
-- 2017-07 to 2017-09 to 2018-01 - so "the previous 5 rows" is not "the previous 5 months".
-- `RANGE BETWEEN INTERVAL '5 months' PRECEDING AND CURRENT ROW` asks Postgres for the real
-- calendar window and is immune to the gaps; a ROWS window would quietly report a 12-month count
-- that spans three calendar years wherever the archive is sparse.

with monthly as (

    select * from {{ ref('int_manufacturer_month') }}

),

windowed as (

    select
        manufacturer_id,
        month_start,
        alert_month,
        reports,
        distinct_drugs,
        central_lab_reports,
        state_lab_reports,

        sum(reports) over (
            partition by manufacturer_id order by month_start
            range between interval '5 months' preceding and current row
        ) as reports_rolling_6m,

        sum(reports) over (
            partition by manufacturer_id order by month_start
            range between interval '11 months' preceding and current row
        ) as reports_rolling_12m,

        sum(reports) over (
            partition by manufacturer_id order by month_start
            rows between unbounded preceding and current row
        ) as reports_cumulative,

        -- the last month before this one in which anything was reported, so a page can say
        -- "first report in 14 months" instead of only showing a bar chart
        max(case when reports > 0 then month_start end) over (
            partition by manufacturer_id order by month_start
            rows between unbounded preceding and 1 preceding
        ) as previous_report_month

    from monthly

)

select
    windowed.manufacturer_id,
    manufacturers.canonical_name,
    manufacturers.state_name,
    windowed.alert_month,
    windowed.month_start,
    windowed.reports,
    windowed.distinct_drugs,
    windowed.central_lab_reports,
    windowed.state_lab_reports,
    windowed.reports_rolling_6m,
    windowed.reports_rolling_12m,
    windowed.reports_cumulative,
    windowed.previous_report_month,
    case
        when windowed.reports > 0 and windowed.previous_report_month is not null
            then (
                extract(year from windowed.month_start) * 12 + extract(month from windowed.month_start)
                - extract(year from windowed.previous_report_month) * 12
                - extract(month from windowed.previous_report_month)
            )::int
    end as months_since_previous_report

from windowed
inner join {{ ref('dim_manufacturer') }} as manufacturers using (manufacturer_id)
