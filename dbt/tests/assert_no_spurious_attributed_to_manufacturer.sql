-- The ethics rule that must never be broken, as a test the build fails on.
--
-- CLAUDE.md Section 6: a spurious (counterfeit) pack carries the name of the company whose
-- product was copied, not of whoever made it. Attributing such a finding to that company would
-- accuse a victim. Phase 3 keeps the printed name in `name_on_pack` and leaves the manufacturer
-- null; Phase 4's star schema therefore has no `manufacturer_id` to count it under.
--
-- That invariant currently holds by construction, in three separate places (silver, the fact's
-- CASE expression, and the manufacturer dimension's filter). This test is what notices if any one
-- of those is ever changed - which is the point: an invariant nothing checks is a comment.

select
    sample_id,
    source_url,
    manufacturer_id,
    name_on_pack
from {{ ref('fact_nsq_sample') }}
where is_spurious
  and manufacturer_id is not null
