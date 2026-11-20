-- Every (product name -> drug class) pair the reviewed vocabulary finds. Unnested, not an array
-- yet: one row per match, so a combination product appears once per class it contains.
--
-- `drug_class` has no source in the CDSCO archive at all (ADR 0014). There is no ATC code and no
-- therapeutic group; `generic_name` is filled for 1,340 of 5,651 product names and holds the whole
-- printed string, not a normalised salt. So the class is a claim a person reviewed and accepted
-- (213 of 215 proposals, `analytics/.../drug_class_review.py`), not something the data reports -
-- and this model is deliberately the only place that claim enters the warehouse.
--
-- **The match is whole-word and the vocabulary holds phrases, not words.** `\y` is Postgres's
-- word boundary, so `ringer` does not match "Ringerol" and `aspirin` does not match "Aspirinox".
-- Phrases matter even more: a word-level vocabulary files "Atorvastatin Calcium Tablets IP" under
-- mineral supplements, because that `calcium` is the salt the statin is formulated as. Hence
-- `calcium carbonate` and `ferrous sulphate` are in the seed and a bare `calcium` never is.
--
-- The same rule is implemented a second time in Python, because the review has to run before this
-- table can exist. What guards the two against drifting apart is not an assertion in SQL but
-- `analytics/tests/test_drug_class_sql.py`, which runs both over every product name in the
-- archive and requires identical answers.

-- Keyed on the printed product name, not on `drug_id`: `dim_drug` is what turns this into an
-- array, so reading dim_drug here would be a circular reference. The grain is the same either
-- way - dim_drug's own grain IS the product name, measured in Phase 4.
-- Materialised as a table, like int_manufacturer_month and for the same reason: three nodes read
-- it (dim_drug, the mart and assert_drug_classes_never_invent_a_class), and as a view each of
-- them re-ran the 5,651 x 213 regex cross join - about 21 seconds apiece. Computed once instead.
{{ config(materialized='table') }}

with drugs as (

    select distinct product_name
    from {{ ref('stg_nsq_sample') }}
    where product_name is not null

),

vocabulary as (

    select
        ingredient,
        drug_class
    from {{ ref('drug_class_vocabulary') }}

),

matches as (

    -- A cross join on purpose: 5,651 names x 213 ingredients is small, and the alternative
    -- (parsing names into tokens first) is what the phrase rule above exists to avoid.
    select
        drugs.product_name,
        vocabulary.ingredient,
        vocabulary.drug_class
    from drugs
    cross join vocabulary
    where drugs.product_name ~* ('\y' || vocabulary.ingredient || '\y')

)

select
    product_name,
    ingredient,
    drug_class
from matches
