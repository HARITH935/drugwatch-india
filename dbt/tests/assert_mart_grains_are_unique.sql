-- Every mart's grain, in one test.
--
-- A mart's grain - what exactly one row means - is its contract with whoever queries it. Break it
-- and nothing errors: numbers simply double. A duplicated manufacturer-month would double every
-- rolling count in the trend mart, and a duplicated (manufacturer, cutoff) would hand Phase 7 the
-- same training example twice and quietly weight it double.
--
-- dbt's built-in `unique` test takes one column, and three of these grains are composite. Writing
-- them as one query keeps the five claims in one place: each branch returns the offending key and
-- says which mart it came from.

with offenders as (

    select 'mart_manufacturer_trend' as mart,
           manufacturer_id || ' @ ' || alert_month as grain,
           count(*) as rows
    from {{ ref('mart_manufacturer_trend') }}
    group by 1, 2 having count(*) > 1

    union all

    select 'mart_ml_features', manufacturer_id || ' @ ' || as_of_month, count(*)
    from {{ ref('mart_ml_features') }}
    group by 1, 2 having count(*) > 1

    union all

    select 'mart_repeat_reported_manufacturers', manufacturer_id, count(*)
    from {{ ref('mart_repeat_reported_manufacturers') }}
    group by 1, 2 having count(*) > 1

    union all

    select 'mart_state_summary', state_id, count(*)
    from {{ ref('mart_state_summary') }}
    group by 1, 2 having count(*) > 1

    union all

    select 'mart_drug_class_failures',
           alert_month_start || ' / ' || drug_class || ' / ' || failure_category,
           count(*)
    from {{ ref('mart_drug_class_failures') }}
    group by 1, 2 having count(*) > 1

)

select * from offenders
