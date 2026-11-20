-- The feature table for Phase 7's manufacturer risk model: one row per manufacturer per monthly
-- cutoff, with the features computed only from what was known at that cutoff.
--
-- Plan §12 defines the task (will this manufacturer appear in at least one NSQ alert in the next
-- 6 months?) and the features. Three rules shape every line below.
--
-- **1. No leakage.** Every feature window ends at `as_of_month` inclusive; the label looks only
-- at months 1-6 AFTER it. The windows are RANGE windows over real dates, so the gaps in CDSCO's
-- publishing (2017-07 then 2017-09 then 2018-01) cannot stretch a "6 month" window across years
-- the way a ROWS window would. Distinct counts (drugs, reporting states) are computed by joining
-- the findings back over the window, because summing per-month distinct counts would double
-- count a drug reported in two different months.
--
-- **2. The label is only present where it is knowable.** A cutoff within 6 months of the end of
-- the archive has an incomplete future, so `label_reported_next_6m` is null there and
-- `label_window_complete` says so. Phase 7 trains on the complete rows and must never fill the
-- others in.
--
-- **3. What the model is not allowed to see.** Spurious findings carry no manufacturer_id, so
-- plan §12's "any spurious-drug association" feature cannot exist here, and that is deliberate:
-- the name on a counterfeit pack is the copied brand (CLAUDE.md Section 6).
--
-- **4. No feature may act as a calendar.** §12's "share of reports by drug class" arrived with
-- Phase 6's reviewed vocabulary (ADR 0014) and is below. The other Phase 7 addition was meant to
-- be "how much CDSCO tested in this window", so the model could tell a company getting worse from
-- the whole archive growing - but measured, the archive's trailing 12-month volume correlates
-- **0.855 with calendar time** (2 findings in the earliest window, 2,517 in the largest). Handing
-- that to the model is handing it a clock, and since the test period is strictly later than the
-- training period, "recent means positive" is a rule that would score well for the wrong reason
-- and would read as a real finding in SHAP. So it enters only as a RATIO -
-- `share_of_archive_reports_12m` - which gives the normalisation without the timeline.
--
-- And the limitation that must travel with any score built on this table: these are *reported*
-- failures from a non-random sample, so they describe reporting history, not true quality.

{% set label_horizon_months = 6 %}

with monthly as (

    select * from {{ ref('int_manufacturer_month') }}

),

archive_end as (

    select max(month_start) as last_month from monthly

),

-- counts over trailing calendar windows, from the dense grid
windows as (

    select
        manufacturer_id,
        month_start,
        alert_month,
        reports,

        sum(reports) over w3 as reports_3m,
        sum(reports) over w6 as reports_6m,
        sum(reports) over w12 as reports_12m,
        sum(reports) over w24 as reports_24m,

        -- the previous 6-month block (months 7-12 back), for the trend feature
        sum(reports) over w12 - sum(reports) over w6 as reports_prior_6m,

        -- the most recent month with anything in it, at or before this cutoff
        max(case when reports > 0 then month_start end) over (
            partition by manufacturer_id order by month_start
            rows between unbounded preceding and current row
        ) as last_report_month,

        -- the label: did anything get reported in the following 6 months?
        sum(reports) over (
            partition by manufacturer_id order by month_start
            range between interval '1 month' following
                      and interval '{{ label_horizon_months }} months' following
        ) as reports_next_6m

    from monthly
    window
        w3 as (partition by manufacturer_id order by month_start
               range between interval '2 months' preceding and current row),
        w6 as (partition by manufacturer_id order by month_start
               range between interval '5 months' preceding and current row),
        w12 as (partition by manufacturer_id order by month_start
                range between interval '11 months' preceding and current row),
        w24 as (partition by manufacturer_id order by month_start
                range between interval '23 months' preceding and current row)

),

-- distinct counts and category shares over the windows 12 months, computed from the findings
-- themselves rather than from per-month aggregates
window_detail as (

    select
        grid.manufacturer_id,
        grid.month_start,
        count(distinct fact.drug_id) as distinct_drugs_12m,
        count(distinct fact.reported_state_name) as distinct_reporting_states_12m,
        count(*) filter (where fact.lab_type = 'Central') as central_lab_reports_12m,
        count(*) filter (where fact.lab_type = 'State') as state_lab_reports_12m
    from monthly as grid
    inner join {{ ref('fact_nsq_sample') }} as fact
        on fact.manufacturer_id = grid.manufacturer_id
       and fact.alert_month_start
           between grid.month_start - interval '11 months' and grid.month_start
    group by grid.manufacturer_id, grid.month_start

),

category_shares as (

    select
        grid.manufacturer_id,
        grid.month_start,
        count(*) as category_mentions_12m,
        count(*) filter (where category = 'Assay') as assay_mentions_12m,
        count(*) filter (where category = 'Dissolution') as dissolution_mentions_12m,
        count(*) filter (where category = 'Sterility') as sterility_mentions_12m,
        count(*) filter (where category = 'Description') as description_mentions_12m
    from monthly as grid
    inner join {{ ref('fact_nsq_sample') }} as fact
        on fact.manufacturer_id = grid.manufacturer_id
       and fact.alert_month_start
           between grid.month_start - interval '11 months' and grid.month_start
    cross join unnest(fact.failure_categories) as category
    group by grid.manufacturer_id, grid.month_start

),

-- Plan §12's "share of reports by drug class", over the same trailing 12 months. The unit is
-- CLASS MENTIONS, not findings: a combination product belongs to two to four classes (ADR 0014),
-- so these shares do not sum to 1, exactly like the failure-category shares above.
--
-- Only the seven classes above 5% of the archive get a column, plus Unclassified. The thin ones
-- (Fluid / electrolyte 3.0%, Antiparasitic 2.5%, and down) are left out on purpose: one
-- manufacturer's 12-month window usually holds a handful of findings, so a share of a 2%-class is
-- almost always exactly 0 or exactly 1 and carries noise rather than signal.
-- `distinct_drug_classes_12m` is carried instead, which says how varied a company's reported
-- range is and does not fall apart on small windows.
class_shares as (

    select
        grid.manufacturer_id,
        grid.month_start,
        count(*) as class_mentions_12m,
        count(distinct drug_class) as distinct_drug_classes_12m,
        count(*) filter (where drug_class = 'Antibiotic') as antibiotic_mentions,
        count(*) filter (
            where drug_class = 'Analgesic / anti-inflammatory'
        ) as analgesic_mentions,
        count(*) filter (where drug_class = 'Gastrointestinal') as gastrointestinal_mentions,
        count(*) filter (where drug_class = 'Vitamin / mineral supplement') as vitamin_mentions,
        count(*) filter (where drug_class = 'Respiratory / cough and cold') as respiratory_mentions,
        count(*) filter (
            where drug_class = 'Antihypertensive / cardiovascular'
        ) as cardiovascular_mentions,
        count(*) filter (
            where drug_class = 'Antihistamine / antiallergic'
        ) as antihistamine_mentions,
        -- `is null`, not = 'Unclassified': dim_drug stores an EMPTY ARRAY when the vocabulary
        -- matched nothing, deliberately, because "nobody could tell" is not a therapeutic class
        -- (ADR 0014). The left join to unnest therefore yields NULL for those findings, and
        -- comparing to the string 'Unclassified' silently counted zero of them.
        count(*) filter (where drug_class is null) as unclassified_mentions
    from monthly as grid
    inner join {{ ref('fact_nsq_sample') }} as fact
        on fact.manufacturer_id = grid.manufacturer_id
       and fact.alert_month_start
           between grid.month_start - interval '11 months' and grid.month_start
    inner join {{ ref('dim_drug') }} as drug on drug.drug_id = fact.drug_id
    -- LEFT join to the unnest: a product the vocabulary never matched has an empty array, and
    -- dropping those rows would make every share a share of only the classifiable findings.
    left join unnest(drug.drug_classes) as classes (drug_class) on true
    group by grid.manufacturer_id, grid.month_start

),

-- How many attributable findings the WHOLE archive published in the same trailing window. Used
-- only as the denominator of a share (see note 4): on its own it is a calendar.
archive_volume as (

    select
        grid.month_start,
        count(*) as archive_reports_12m
    from (select distinct month_start from monthly) as grid
    inner join {{ ref('fact_nsq_sample') }} as fact
        on fact.manufacturer_id is not null
       and fact.alert_month_start
           between grid.month_start - interval '11 months' and grid.month_start
    group by grid.month_start

)

select
    windows.manufacturer_id,
    windows.alert_month as as_of_month,
    windows.month_start as as_of_month_start,

    -- features: what was known at the cutoff
    windows.reports_3m,
    windows.reports_6m,
    windows.reports_12m,
    windows.reports_24m,
    windows.reports_prior_6m,
    windows.reports_6m - windows.reports_prior_6m as reports_trend_6m,
    (
        extract(year from windows.month_start) * 12 + extract(month from windows.month_start)
        - extract(year from windows.last_report_month) * 12
        - extract(month from windows.last_report_month)
    )::int as months_since_last_report,

    coalesce(window_detail.distinct_drugs_12m, 0) as distinct_drugs_12m,
    coalesce(window_detail.distinct_reporting_states_12m, 0) as distinct_reporting_states_12m,
    coalesce(window_detail.central_lab_reports_12m, 0) as central_lab_reports_12m,
    coalesce(window_detail.state_lab_reports_12m, 0) as state_lab_reports_12m,
    -- a ratio, not a count, so a big and a small manufacturer are comparable. Null, not 0, when
    -- there is nothing to divide: no reports in the window is not "0% central".
    case
        when coalesce(window_detail.central_lab_reports_12m, 0)
             + coalesce(window_detail.state_lab_reports_12m, 0) > 0
        then round(
            window_detail.central_lab_reports_12m::numeric
            / (window_detail.central_lab_reports_12m + window_detail.state_lab_reports_12m), 4)
    end as central_lab_share_12m,

    -- Shares of CATEGORY MENTIONS, not of reports: 22.6% of findings name more than one failed
    -- test (ADR 0009), so these do not sum to 1 and the column names say "mentions".
    category_shares.category_mentions_12m,
    case when category_shares.category_mentions_12m > 0
        then round(category_shares.assay_mentions_12m::numeric
                   / category_shares.category_mentions_12m, 4) end as assay_share_12m,
    case when category_shares.category_mentions_12m > 0
        then round(category_shares.dissolution_mentions_12m::numeric
                   / category_shares.category_mentions_12m, 4) end as dissolution_share_12m,
    case when category_shares.category_mentions_12m > 0
        then round(category_shares.sterility_mentions_12m::numeric
                   / category_shares.category_mentions_12m, 4) end as sterility_share_12m,
    case when category_shares.category_mentions_12m > 0
        then round(category_shares.description_mentions_12m::numeric
                   / category_shares.category_mentions_12m, 4) end as description_share_12m,

    -- Plan §12's drug-class shares (ADR 0014's vocabulary). Shares of CLASS MENTIONS, so they do
    -- not sum to 1; null, not 0, where the window holds no findings to divide.
    class_shares.class_mentions_12m,
    coalesce(class_shares.distinct_drug_classes_12m, 0) as distinct_drug_classes_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.antibiotic_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as antibiotic_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.analgesic_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as analgesic_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.gastrointestinal_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as gastrointestinal_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.vitamin_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as vitamin_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.respiratory_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as respiratory_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.cardiovascular_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as cardiovascular_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.antihistamine_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as antihistamine_share_12m,
    case when class_shares.class_mentions_12m > 0
        then round(class_shares.unclassified_mentions::numeric
                   / class_shares.class_mentions_12m, 4) end as unclassified_share_12m,

    -- This company's share of everything the archive reported in the window. A ratio on purpose:
    -- the raw archive volume correlates 0.855 with calendar time and would be a clock (note 4).
    case when archive_volume.archive_reports_12m > 0
        then round(windows.reports_12m::numeric
                   / archive_volume.archive_reports_12m, 6) end as share_of_archive_reports_12m,

    -- the label, and whether it is knowable at all
    windows.month_start + interval '{{ label_horizon_months }} months'
        <= archive_end.last_month as label_window_complete,
    case
        when windows.month_start + interval '{{ label_horizon_months }} months'
             <= archive_end.last_month
        then coalesce(windows.reports_next_6m, 0) > 0
    end as label_reported_next_6m

from windows
cross join archive_end
left join window_detail using (manufacturer_id, month_start)
left join category_shares using (manufacturer_id, month_start)
left join class_shares using (manufacturer_id, month_start)
left join archive_volume using (month_start)
