-- When this warehouse was last rebuilt, and whether that run passed its checks.
--
-- Every public dashboard has to answer "how old is this?", and CLAUDE.md §6 requires the source
-- and the alert month to travel with the data. The honest answer lives in Phase 5's run log, not
-- in a timestamp inside gold: a row's write time says when it was written, while the run log knows
-- whether the run that wrote it actually passed Great Expectations and `dbt build`.
--
-- This mart exists so the dashboards can show that without Superset being granted access to the
-- `ops` schema. Superset reads gold only; one curated row crosses the boundary, not the whole
-- operational log.
--
-- The **latest successful** run, not the latest run: a failed run leaves the warehouse holding
-- whatever the last good one produced, so reporting its timestamp would overstate freshness.

with successful_runs as (

    select *
    from {{ source('ops', 'pipeline_run') }}
    where status = 'success'

),

latest as (

    select *
    from successful_runs
    order by recorded_at desc
    limit 1

)

select
    recorded_at as last_updated_at,
    to_char(recorded_at, 'DD Mon YYYY') as last_updated_on,
    dag_id as updated_by_pipeline,
    silver_rows as findings_loaded,
    raw_files as source_files_in_the_archive,
    dbt_nodes_passed,
    dbt_nodes_total,
    quality_check as quality_gate,
    -- How many days ago, so a dashboard can say "updated 3 days ago" without doing date maths in
    -- a chart. CDSCO publishes monthly, so anything over ~45 days means the pipeline has stopped.
    (current_date - recorded_at::date) as days_since_update
from latest
