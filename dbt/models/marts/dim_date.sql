-- A row per calendar day, so every date in the warehouse can be grouped by year, quarter or
-- month without each dashboard inventing its own date arithmetic.
--
-- Why a table of dates at all: Superset and the API ask things like "NSQ reports per quarter" or
-- "batches expiring this year". With a date dimension that is a join and a GROUP BY; without one,
-- every query repeats its own `date_trunc`/`extract` logic and they drift apart. It also gives
-- months with zero reports somewhere to come from, so a time series shows the gap instead of
-- silently skipping it.
--
-- The range is derived from the data, not hardcoded, so it cannot go stale: it spans whole years
-- from the earliest to the latest date anywhere in the fact (alert months, manufacture dates and
-- expiry dates - expiry reaches 2034, nine years past the newest alert).

with bounds as (

    select
        date_trunc('year', least(min(alert_month_start), min(mfg_date), min(expiry_date)))::date
            as first_day,
        (date_trunc('year', greatest(max(alert_month_start), max(mfg_date), max(expiry_date)))
            + interval '1 year - 1 day')::date as last_day
    from {{ ref('stg_nsq_sample') }}

),

days as (

    select generate_series(first_day, last_day, interval '1 day')::date as date_day
    from bounds

),

final as (

    select
        -- YYYYMMDD as an integer: the classic star-schema date key. It is readable in a query
        -- result (20250601 is obviously 1 June 2025), sorts chronologically, and joins faster
        -- than text.
        to_char(date_day, 'YYYYMMDD')::int as date_id,
        date_day,
        extract(year from date_day)::int as year_number,
        extract(quarter from date_day)::int as quarter_number,
        extract(month from date_day)::int as month_number,
        to_char(date_day, 'Mon') as month_name,
        to_char(date_day, 'YYYY-MM') as year_month,  -- matches `alert_month` in the fact
        date_trunc('month', date_day)::date as month_start,
        extract(day from date_day)::int as day_of_month,
        extract(isodow from date_day)::int as iso_day_of_week,  -- 1 = Monday
        to_char(date_day, 'Dy') as day_name
    from days

)

select * from final
