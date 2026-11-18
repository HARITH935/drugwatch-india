-- One row per medicine, as CDSCO printed its name.
--
-- The grain is the product name, and that is a measured choice, not an assumption: across all
-- 7,126 rows, no product name ever carries two different dosage forms, generic names, brand names
-- or strength lists (checked in SQL first - 0 exceptions). So the name determines the rest, and a
-- wider grain would only invent duplicates.
--
-- What this does NOT do is decide that two differently-printed names are the same medicine.
-- "Paracetamol Tablets IP 500 mg" and "Paracetamol Tab. 500mg" stay two rows. Resolving those is
-- the drug equivalent of Phase 3 step 5, needs the same kind of reviewed evidence, and is not
-- something to slip in unannounced.
--
-- `drug_class` from Section 8.1 is missing on purpose: nothing in the archive classifies a drug
-- (no ATC or therapeutic-class source has been ingested), and inventing classes from name
-- fragments would be a guess presented as a fact. `mart_drug_class_failures` needs this resolved
-- first - it is an open question for Harith, recorded in PROGRESS.md.

with samples as (

    select * from {{ ref('stg_nsq_sample') }}

),

final as (

    select
        md5(product_name) as drug_id,
        product_name,

        -- Filled only where Phase 3 could split the name without guessing (~20% of rows), so a
        -- null here means "not stated unambiguously", never "no brand".
        generic_name,
        brand_name,
        dosage_form,
        strengths

    from samples
    -- grouping by all of them is free (they are constant per product_name, proven above) and
    -- says so in the code. No count of findings here, for the same reason as dim_manufacturer:
    -- a dimension describes a thing, the marts do the counting.
    group by product_name, generic_name, brand_name, dosage_form, strengths

)

select * from final
