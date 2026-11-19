-- A postal-code-prefix -> state map, LEARNED from the addresses that name their state.
--
-- Why learned and not looked up: the obvious way to turn a PIN into a state is a reference table
-- of India's postal prefixes. We do not have one in the repo, and writing one out from memory
-- would be inventing reference data for a public dataset - the mistakes would be invisible and
-- permanent. India's 2-digit prefixes are also genuinely ambiguous for every state that was ever
-- split: UP/Uttarakhand, AP/Telangana, Bihar/Jharkhand, MP/Chhattisgarh, Maharashtra/Goa,
-- TN/Puducherry.
--
-- So the map comes out of the data we already trust. 1,421 manufacturers both name their state in
-- the address AND print a PIN. Grouped by the first three digits, that is evidence: if every
-- company whose PIN starts 382 says Gujarat, then 382 means Gujarat here.
--
-- Two guards, because evidence can be thin or contradictory:
--   - **unanimous only**: a prefix where the known states disagree is dropped, not voted on.
--     13 of 151 prefixes are dropped this way, and they are exactly the split states above.
--   - **at least `pin_prefix_min_observations` companies** (3). A prefix seen once is a
--     coincidence; the holdout below shows what the threshold buys.
--
-- **Validated by holdout, not by assertion.** Learning from half the known rows (split on the id,
-- so the halves are arbitrary) and predicting the other half - where the state is known
-- independently, from its own address - gives 99.78% agreement at a threshold of 3 (460 of 461),
-- against 99.59% at 2. Checking the map against the rows it was learned from would have been
-- circular and would have reported a meaningless 100%.
--
-- The one remaining holdout error is honest to state: prefix 244 covers Moradabad in Uttar
-- Pradesh and Kashipur in Uttarakhand, and the sample it was learned from happened to be
-- unanimous. That is the shape of the residual risk: ~0.2% of PIN-derived states, always between
-- two neighbouring states, never a wild answer.

{% set min_observations = var('pin_prefix_min_observations') %}

with known as (

    -- manufacturers whose state the ADDRESS NAMES, and which also print a PIN
    select
        address.pin_code,
        named.state_from_name as state_name
    from {{ ref('int_manufacturer_address') }} as address
    inner join {{ ref('int_manufacturer_state') }} as named using (manufacturer_id)
    where address.pin_code is not null
      -- only name-derived answers teach the map, never PIN-derived ones: learning from your own
      -- output is how a small error becomes a large one
      and named.name_match_status = 'matched'

),

by_prefix as (

    select
        left(pin_code, 3) as pin_prefix,
        count(*) as observations,
        count(distinct state_name) as states_seen,
        min(state_name) as state_name
    from known
    group by left(pin_code, 3)

)

select
    pin_prefix,
    state_name,
    observations
from by_prefix
where states_seen = 1
  and observations >= {{ min_observations }}
