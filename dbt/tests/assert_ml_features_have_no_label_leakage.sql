-- The feature table may not know the future.
--
-- `mart_ml_features` computes its features with RANGE windows over a dense month grid, and its
-- label with a forward window. Both are easy to get subtly wrong - an off-by-one in a window
-- frame, or a ROWS frame where a RANGE frame was meant, leaks months the model should not see.
-- A model trained on leaked features scores beautifully and is worthless.
--
-- So this recomputes the same numbers a completely different way - joining the findings back by
-- date range, no window functions at all - and returns every row where the two disagree. It is
-- the manual check from step 3 piece 3 turned into something `dbt build` fails on, which is the
-- whole point of step 4: a verification nobody re-runs is a memory, not a guarantee.
--
-- Checked: reports_6m, reports_12m, the label itself, and that the label is null exactly where
-- the archive cannot answer yet.

with findings as (

    select manufacturer_id, alert_month_start
    from {{ ref('fact_nsq_sample') }}
    where manufacturer_id is not null

),

features as (select * from {{ ref('mart_ml_features') }}),

recomputed as (

    select
        features.manufacturer_id,
        features.as_of_month,
        count(findings.*) filter (
            where findings.alert_month_start
                  between features.as_of_month_start - interval '5 months'
                      and features.as_of_month_start
        ) as reports_6m,
        count(findings.*) filter (
            where findings.alert_month_start
                  between features.as_of_month_start - interval '11 months'
                      and features.as_of_month_start
        ) as reports_12m,
        count(findings.*) filter (
            where findings.alert_month_start > features.as_of_month_start
              and findings.alert_month_start
                  <= features.as_of_month_start + interval '6 months'
        ) as reports_next_6m
    from features
    left join findings using (manufacturer_id)
    group by features.manufacturer_id, features.as_of_month

)

select
    features.manufacturer_id,
    features.as_of_month,
    features.reports_6m,
    recomputed.reports_6m as recomputed_6m,
    features.reports_12m,
    recomputed.reports_12m as recomputed_12m,
    features.label_reported_next_6m,
    recomputed.reports_next_6m > 0 as recomputed_label
from features
inner join recomputed using (manufacturer_id, as_of_month)
where features.reports_6m <> recomputed.reports_6m
   or features.reports_12m <> recomputed.reports_12m
   or (features.label_window_complete
       and features.label_reported_next_6m is distinct from (recomputed.reports_next_6m > 0))
   or (not features.label_window_complete and features.label_reported_next_6m is not null)
