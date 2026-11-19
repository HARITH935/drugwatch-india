-- Every failure category must be one of ADR 0009's fifteen.
--
-- `failure_categories` is an array (22.6% of findings name more than one failed test), so dbt's
-- built-in `accepted_values` cannot check it - that test compares a column to a list, not a list
-- to a list. Unnesting and checking what comes out is the array version of the same idea.
--
-- The vocabulary is **restated here, not imported** from the model that produces it. That is
-- deliberate, and the same choice the Phase 3 Great Expectations suite made: a test that reads
-- its expectations from the code under test cannot fail. If someone adds a sixteenth category,
-- this test is supposed to break and make them say so out loud.

with vocabulary as (

    select unnest(array[
        'Assay', 'Description', 'Disintegration', 'Dissolution', 'Identification',
        'Labelling', 'Other', 'Particulate', 'pH', 'Physical', 'Related substances',
        'Spurious', 'Sterility', 'Uniformity', 'Water'
    ]) as category

),

used as (

    select
        sample_id,
        source_url,
        category
    from {{ ref('fact_nsq_sample') }},
        unnest(failure_categories) as category

)

select *
from used
where category not in (select category from vocabulary)
