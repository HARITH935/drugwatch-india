-- Which laboratory tests fail, per drug class, across the whole archive.
--
-- `mart_drug_class_failures` (plan §8.2) is the same question with the month dimension kept, for
-- Phase 7's features and Phase 9's reports. This is the version a dashboard can draw: 27 classes
-- across 101 months is 4,333 rows and no readable chart, while 27 classes x 16 categories is one.
--
-- The unit is **category mentions**, not findings, and the column says so. A finding naming three
-- failed tests contributes to three categories (ADR 0009), so these do not sum to the archive's
-- finding count - `pct_of_class` is each category's share of its own class's findings, which is
-- the number a reader actually wants ("of the antibiotic findings, how many failed dissolution").

with finding_class_category as (

    select
        samples.sample_id,
        coalesce(classes.drug_class, 'Unclassified') as drug_class,
        coalesce(category, 'Other') as failure_category
    from {{ ref('fact_nsq_sample') }} as samples
    inner join {{ ref('dim_drug') }} as drugs using (drug_id)
    left join unnest(drugs.drug_classes) as classes (drug_class) on true
    left join unnest(samples.failure_categories) as category on true

),

class_totals as (

    select
        drug_class,
        count(distinct sample_id) as findings_in_class
    from finding_class_category
    group by drug_class

),

final as (

    select
        pairs.drug_class,
        pairs.failure_category,
        count(distinct pairs.sample_id) as mentions,
        class_totals.findings_in_class,
        round(
            100.0 * count(distinct pairs.sample_id) / class_totals.findings_in_class, 1
        ) as pct_of_class
    from finding_class_category as pairs
    inner join class_totals using (drug_class)
    group by pairs.drug_class, pairs.failure_category, class_totals.findings_in_class

)

select * from final
