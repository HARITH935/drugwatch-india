-- Nothing may be lost between the loaded silver table and the fact.
--
-- The fact is a straight select over staging, so every `sample_id` in staging must appear in it
-- exactly once and vice versa. This is the test that would catch a WHERE clause added to the
-- fact "temporarily", or a join to a dimension accidentally turned from LEFT into INNER - which
-- would silently drop the 128 findings that have no manufacturer printed.
--
-- A full outer join rather than two counts: equal counts can hide an equal number of additions
-- and losses, and this names the rows.

with staging as (select sample_id from {{ ref('stg_nsq_sample') }}),
fact as (select sample_id from {{ ref('fact_nsq_sample') }})

select
    staging.sample_id as staging_sample_id,
    fact.sample_id as fact_sample_id
from staging
full outer join fact using (sample_id)
where staging.sample_id is null
   or fact.sample_id is null
