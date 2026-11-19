-- Findings per alert month, beside the number of laboratories that reported them.
--
-- This mart exists because of what the Phase 6 exploration found: **findings and the number of
-- distinct reporting laboratories correlate at r = 0.964 across years** (docs/analytics-findings.md
-- §1). A chart of findings per month alone reads as "medicine is getting worse"; this data does not
-- support that, and what actually grew fastest is surveillance.
--
-- So the two series live in one mart, deliberately: a dashboard built on this table cannot plot the
-- findings line without the lab count being one column away. Splitting them into two marts would
-- make the misleading chart the easier one to build.
--
-- One row per published alert month. Months CDSCO never published are absent rather than zero -
-- 101 of the 111 calendar months spanned - because "no alert was published" and "no batches failed"
-- are different statements and a zero would assert the second.

with findings as (

    select * from {{ ref('fact_nsq_sample') }}

)

select
    alert_month,
    alert_month_start,

    count(*) as findings,
    count(*) filter (where lab_type = 'Central') as central_lab_findings,
    count(*) filter (where lab_type = 'State') as state_lab_findings,
    count(*) filter (where is_spurious) as spurious_findings,

    -- the honesty columns
    count(distinct reported_by) as reporting_labs,
    count(distinct reported_state_name) as reporting_states,

    count(distinct manufacturer_id) as manufacturers_reported,
    count(distinct drug_id) as products_reported

from findings
group by alert_month, alert_month_start
