-- Plan §9 step 4's own example: expiry must come after manufacture.
--
-- A singular test is just a query that selects the rows that should not exist: dbt fails the test
-- if it returns anything. So this is the violation, not the rule.
--
-- It is written as a CONSISTENCY check rather than a flat rule, because the archive genuinely
-- contains impossible dates - CDSCO prints typos, and Phase 3 found 17 of them. Phase 3's answer
-- was `dates_valid`, a flag that is false exactly when the pair makes no sense. So the thing that
-- must never happen is not "expiry <= mfg" but "expiry <= mfg while dates_valid says otherwise":
-- a real typo passing itself off as a valid date.

select
    sample_id,
    source_url,
    mfg_date,
    expiry_date,
    dates_valid
from {{ ref('fact_nsq_sample') }}
where mfg_date is not null
  and expiry_date is not null
  and expiry_date <= mfg_date
  and dates_valid is not false
