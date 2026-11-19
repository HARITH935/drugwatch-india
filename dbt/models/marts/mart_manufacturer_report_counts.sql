-- How many companies have how many findings: the archive's shape, in one small table.
--
-- The exploration found the archive is a long tail, not a league table: **1,521 of 2,609
-- manufacturers (58%) appear exactly once**, the median company has one finding, and the top 10%
-- hold 45.9% (docs/analytics-findings.md §2).
--
-- That matters because a "top 10 manufacturers" chart describes 10 companies out of 2,609 while
-- inviting precisely the verdict CLAUDE.md §6 forbids. This mart is what goes next to such a chart
-- so a reader can see how unrepresentative the top of any ranking is.
--
-- Grain: one row per distinct "number of findings" value, with how many companies sit there.

with per_manufacturer as (

    select
        manufacturer_id,
        count(*) as findings
    from {{ ref('fact_nsq_sample') }}
    where manufacturer_id is not null  -- spurious packs name no maker (CLAUDE.md §6)
    group by manufacturer_id

),

totals as (

    select
        count(*) as manufacturers_total,
        sum(findings) as findings_total
    from per_manufacturer

)

select
    per_manufacturer.findings as findings_per_manufacturer,
    count(*) as manufacturers,
    sum(per_manufacturer.findings) as findings,
    round(100.0 * count(*) / totals.manufacturers_total, 2) as pct_of_manufacturers,
    round(100.0 * sum(per_manufacturer.findings) / totals.findings_total, 2) as pct_of_findings
from per_manufacturer
cross join totals
group by per_manufacturer.findings, totals.manufacturers_total, totals.findings_total
order by per_manufacturer.findings
