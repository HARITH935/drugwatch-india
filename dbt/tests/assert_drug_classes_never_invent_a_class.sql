-- Every class in the warehouse must be one a person actually accepted.
--
-- `drug_class` is the only field in the gold layer that the CDSCO archive does not report: it
-- comes from a reviewed vocabulary, 213 entries accepted one batch at a time (ADR 0014). That
-- makes a class appearing from anywhere else - a hand-edited seed, a model that defaults a value,
-- a future join - the exact failure this design exists to prevent. The warehouse must never name
-- a therapeutic class that no reviewer signed off.
--
-- `Unclassified` is allowed in the mart and only there: it is the reported remainder, not a class.
-- Restating the rule in SQL rather than importing the vocabulary is deliberate, the same choice as
-- assert_failure_categories_in_vocabulary - a test that reads the thing it is checking proves
-- nothing.

with reviewed as (

    select drug_class from {{ ref('drug_class_vocabulary') }}

),

in_the_warehouse as (

    select distinct drug_class, 'int_drug_class' as model
    from {{ ref('int_drug_class') }}

    union all

    select distinct unnest(drug_classes), 'dim_drug'
    from {{ ref('dim_drug') }}

    union all

    select distinct drug_class, 'mart_drug_class_failures'
    from {{ ref('mart_drug_class_failures') }}
    where drug_class != 'Unclassified'

)

select
    in_the_warehouse.drug_class,
    in_the_warehouse.model
from in_the_warehouse
where in_the_warehouse.drug_class not in (select drug_class from reviewed)
