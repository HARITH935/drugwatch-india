-- One row per manufacturer per month, including the months with nothing in them.
--
-- Shared by mart_manufacturer_trend and mart_ml_features, which both need the same grid: rolling
-- and trailing windows are only correct over a DENSE series of months. If a manufacturer's
-- quiet months are simply missing, "reports in the last 6 months" silently becomes "reports in
-- the last 6 months that happen to have reports" - which is never zero, and is the classic way a
-- time-window feature leaks or flatters itself.
--
-- The grid runs from each manufacturer's first alert month to the last month in the whole
-- archive, not to its own last month: a company going quiet is a real signal, and stopping the
-- series at its final finding would delete exactly that.
--
-- Spurious reports are absent for free: they carry no manufacturer_id (CLAUDE.md Section 6), so
-- joining on it leaves them out. Nothing here could attribute a counterfeit pack to the company
-- whose name was copied, even by accident.
--
-- Materialised as a table, unlike the other intermediate models: it is a cross join read twice,
-- so storing ~190k rows once is cheaper than recomputing it per reader.

{{ config(materialized='table') }}

with findings as (

    select
        fact.manufacturer_id,
        fact.alert_month_start,
        fact.sample_id,
        fact.drug_id,
        fact.lab_type,
        fact.reported_state_name,
        fact.failure_categories
    from {{ ref('fact_nsq_sample') }} as fact
    where fact.manufacturer_id is not null

),

-- the archive's own month axis, so the grid never invents a month CDSCO never published in
archive_months as (

    select distinct alert_month_start as month_start
    from {{ ref('fact_nsq_sample') }}

),

manufacturer_span as (

    select
        manufacturer_id,
        min(alert_month_start) as first_month,
        (select max(month_start) from archive_months) as last_month
    from findings
    group by manufacturer_id

),

grid as (

    select
        manufacturer_span.manufacturer_id,
        archive_months.month_start
    from manufacturer_span
    inner join archive_months
        on archive_months.month_start between manufacturer_span.first_month
                                          and manufacturer_span.last_month

),

-- one row per (manufacturer, month, category), so a finding naming three failures counts once
-- for each of them. Reports and category mentions are therefore different units, and the marts
-- say so in their column names.
category_mentions as (

    select
        manufacturer_id,
        alert_month_start,
        category
    from findings,
        unnest(failure_categories) as category

),

monthly as (

    select
        manufacturer_id,
        alert_month_start,
        count(*) as reports,
        count(distinct drug_id) as distinct_drugs,
        count(distinct reported_state_name) as distinct_reporting_states,
        count(*) filter (where lab_type = 'Central') as central_lab_reports,
        count(*) filter (where lab_type = 'State') as state_lab_reports
    from findings
    group by manufacturer_id, alert_month_start

),

monthly_categories as (

    select
        manufacturer_id,
        alert_month_start,
        count(*) filter (where category = 'Assay') as assay_mentions,
        count(*) filter (where category = 'Dissolution') as dissolution_mentions,
        count(*) filter (where category = 'Sterility') as sterility_mentions,
        count(*) filter (where category = 'Description') as description_mentions,
        count(*) as category_mentions
    from category_mentions
    group by manufacturer_id, alert_month_start

)

select
    grid.manufacturer_id,
    grid.month_start,
    to_char(grid.month_start, 'YYYY-MM') as alert_month,

    -- coalesce, because a month with no findings is a zero, not an unknown
    coalesce(monthly.reports, 0) as reports,
    coalesce(monthly.distinct_drugs, 0) as distinct_drugs,
    coalesce(monthly.distinct_reporting_states, 0) as distinct_reporting_states,
    coalesce(monthly.central_lab_reports, 0) as central_lab_reports,
    coalesce(monthly.state_lab_reports, 0) as state_lab_reports,
    coalesce(monthly_categories.category_mentions, 0) as category_mentions,
    coalesce(monthly_categories.assay_mentions, 0) as assay_mentions,
    coalesce(monthly_categories.dissolution_mentions, 0) as dissolution_mentions,
    coalesce(monthly_categories.sterility_mentions, 0) as sterility_mentions,
    coalesce(monthly_categories.description_mentions, 0) as description_mentions

from grid
left join monthly
    on grid.manufacturer_id = monthly.manufacturer_id
   and grid.month_start = monthly.alert_month_start
left join monthly_categories
    on grid.manufacturer_id = monthly_categories.manufacturer_id
   and grid.month_start = monthly_categories.alert_month_start
