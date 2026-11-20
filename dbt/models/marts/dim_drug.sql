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
-- `drug_classes` is Section 8.1's `drug_class`, and it is plural for a measured reason: 530 of
-- 7,126 findings print ingredients from two to four different classes, so one column would need a
-- priority rule nobody can defend ("why does Antibiotic outrank Probiotic?"). Same shape as
-- `failure_categories` (ADR 0009), with the same obligation on anything that counts it: a
-- combination product is counted under each of its classes, so the classes add up to more than
-- the total, and every chart has to say so.
--
-- It is also the one column here that the archive does not report. Nothing in CDSCO classifies a
-- medicine, so these come from a vocabulary of 213 ingredient phrases that a person accepted one
-- batch at a time (ADR 0014). An empty array means the vocabulary matched nothing - 1,382
-- findings, mostly brand-named products whose pack prints no ingredient ("Zylinta Syrup") - and
-- it is an empty array rather than the string 'Unclassified' because "nobody could tell" is not
-- a therapeutic class. The marts turn it into a reported `Unclassified` count; this table does
-- not pretend to know.

with samples as (

    select * from {{ ref('stg_nsq_sample') }}

),

-- Collapsed to one row per product name, sorted so two products with the same classes always
-- produce the identical array - otherwise anything grouping on it sees two groups where there is
-- one.
classes as (

    select
        product_name,
        array_agg(distinct drug_class order by drug_class) as drug_classes
    from {{ ref('int_drug_class') }}
    group by product_name

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
        strengths,

        -- coalesce, not a null: "the vocabulary matched nothing" is an empty set of classes, and
        -- a null here would make every consumer handle a third case that does not exist.
        coalesce(classes.drug_classes, array[]::text[]) as drug_classes

    from samples
    left join classes using (product_name)
    -- grouping by all of them is free (they are constant per product_name, proven above) and
    -- says so in the code. No count of findings here, for the same reason as dim_manufacturer:
    -- a dimension describes a thing, the marts do the counting.
    group by product_name, generic_name, brand_name, dosage_form, strengths, classes.drug_classes

)

select * from final
