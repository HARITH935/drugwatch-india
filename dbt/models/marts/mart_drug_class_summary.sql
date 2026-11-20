-- One row per drug class: how many findings it covers, and what most commonly failed in it.
--
-- This mart exists so that no chart ever has to sum a column that would overcount.
-- `mart_drug_class_failures` is correct but its grain is class x failure category x month, and a
-- finding with two ingredients and two failed tests is four rows there - so `sum(findings)` on a
-- dashboard would silently inflate every class. Here the grain is one row per class and `findings`
-- is a distinct count, so summing it is safe and a bar chart cannot get it wrong by default.
--
-- `Unclassified` is a row here like any other (1,382 findings, 19.4%): the number a reader needs
-- most is the one saying how much of the archive this whole exercise does not reach.
--
-- The classes still add up to more than the total, because 530 findings carry two to four classes
-- (ADR 0014). `pct_of_findings` is each class's share of all findings, not a slice of a pie, and
-- the dashboard note says so.

with findings as (

    select
        samples.sample_id,
        samples.failure_categories,
        samples.drug_id
    from {{ ref('fact_nsq_sample') }} as samples

),

-- Left join to the unnest, so a finding the vocabulary never matched keeps its place under
-- `Unclassified` instead of vanishing from the denominator.
finding_class as (

    select
        findings.sample_id,
        findings.failure_categories,
        drugs.drug_id,
        coalesce(classes.drug_class, 'Unclassified') as drug_class
    from findings
    inner join {{ ref('dim_drug') }} as drugs using (drug_id)
    left join unnest(drugs.drug_classes) as classes (drug_class) on true

),

total as (

    select count(*) as findings from {{ ref('fact_nsq_sample') }}

),

-- How much of the archive the whole vocabulary never reaches. Counted from the findings whose
-- product matched nothing, not as "total minus the sum of the classes": the classes overlap, so
-- that subtraction would be wrong in a way nobody would notice.
unreached as (

    select count(*) as findings
    from {{ ref('fact_nsq_sample') }} as samples
    inner join {{ ref('dim_drug') }} as drugs using (drug_id)
    where cardinality(drugs.drug_classes) = 0

),

per_class as (

    select
        drug_class,
        count(distinct sample_id) as findings,
        count(distinct drug_id) as products
    from finding_class
    group by drug_class

),

-- The commonest failed test in each class, with how much of the class it accounts for. Category
-- mentions, not findings: a finding naming three failed tests contributes to three categories
-- (ADR 0009), so this shares `mart_...failures`' unit and not `findings`'.
category_rank as (

    select
        finding_class.drug_class,
        category as failure_category,
        count(*) as mentions,
        row_number() over (
            partition by finding_class.drug_class order by count(*) desc, category
        ) as rank
    from finding_class
    left join unnest(finding_class.failure_categories) as category on true
    group by finding_class.drug_class, category

),

final as (

    select
        per_class.drug_class,
        -- The two headline numbers, repeated on every row and charted with MAX - the same shape
        -- mart_lab_vs_maker_state uses for its own headline. A dashboard needs them beside the
        -- bars, and recomputing them in a chart's SQL is where a denominator goes wrong.
        total.findings - unreached.findings as findings_classified,
        unreached.findings as findings_unclassified,
        round(100.0 * (total.findings - unreached.findings) / total.findings, 1) as pct_classified,
        per_class.findings,
        per_class.products,
        round(100.0 * per_class.findings / total.findings, 1) as pct_of_findings,
        category_rank.failure_category as commonest_failure,
        category_rank.mentions as commonest_failure_mentions,
        -- Measured against the class's own findings, so it reads as "of this class's findings,
        -- this share had that test fail" rather than a share of the whole archive.
        round(100.0 * category_rank.mentions / per_class.findings, 1) as commonest_failure_pct
    from per_class
    cross join total
    cross join unreached
    left join category_rank
        on per_class.drug_class = category_rank.drug_class
        and category_rank.rank = 1

)

select * from final
