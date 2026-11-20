-- Section 8.2's `mart_drug_class_failures`: which laboratory tests fail, per drug class, per
-- alert month.
--
-- **Read the two "total" columns, not one.** A finding belongs to as many classes as it has
-- ingredients (530 of 7,126 do) and names as many failure categories as the laboratory reported
-- (ADR 0009, 22% name more than one). So this table is a count of class x category pairs, and
-- **summing `findings` across classes or across categories overcounts**. `findings_in_class` and
-- `findings_in_month` are carried on every row so a chart can show a share without re-deriving a
-- denominator that would be wrong.
--
-- **Unclassified is a row here, not a gap.** 1,382 findings (19.4%) match no ingredient in the
-- vocabulary - mostly brand-named products whose pack prints no ingredient ("Zylinta Syrup").
-- Dropping them would quietly change the denominator of every percentage on the dashboard, so
-- they are carried as the class `Unclassified` and the dashboard says what it means.
--
-- **Four of the classes are not therapeutic**, and that is the point of them: CDSCO tests cotton
-- wool, gauze, syringes, hand sanitiser, soap and hair colour. `Surgical consumable or device`,
-- `Antiseptic / disinfectant`, `Cosmetic or toiletry` and `Pharmaceutical raw material` say so
-- rather than letting a reader assume every row is a medicine (ADR 0014).

with findings as (

    select
        samples.sample_id,
        samples.alert_month_start,
        samples.failure_categories,
        samples.drug_id
    from {{ ref('fact_nsq_sample') }} as samples

),

-- One row per finding per class. `drug_classes` is an empty array when the vocabulary matched
-- nothing, and unnesting an empty array drops the row - so this is a LEFT join to the unnest
-- (`on true`), which keeps the finding and leaves the class null for the coalesce to label.
-- Filtering instead would quietly change the denominator of every percentage on the dashboard.
finding_class as (

    select
        findings.sample_id,
        findings.alert_month_start,
        findings.failure_categories,
        coalesce(drugs.drug_class, 'Unclassified') as drug_class
    from findings
    left join {{ ref('dim_drug') }} as dim using (drug_id)
    left join unnest(dim.drug_classes) as drugs (drug_class) on true

),

-- ...and then one row per finding per class per failure category. A finding with no category at
-- all still counts, under the vocabulary's own 'Other' (ADR 0009 never leaves the array empty,
-- but the coalesce means a future change cannot silently drop rows).
finding_class_category as (

    select
        finding_class.sample_id,
        finding_class.alert_month_start,
        finding_class.drug_class,
        coalesce(category, 'Other') as failure_category
    from finding_class
    left join unnest(finding_class.failure_categories) as category on true

),

denominators as (

    select
        drug_class,
        count(distinct sample_id) as findings_in_class
    from finding_class
    group by drug_class

),

per_month as (

    select
        alert_month_start,
        count(distinct sample_id) as findings_in_month
    from finding_class
    group by alert_month_start

),

final as (

    select
        pairs.alert_month_start,
        pairs.drug_class,
        pairs.failure_category,
        count(distinct pairs.sample_id) as findings,
        denominators.findings_in_class,
        per_month.findings_in_month
    from finding_class_category as pairs
    inner join denominators using (drug_class)
    inner join per_month using (alert_month_start)
    group by
        pairs.alert_month_start,
        pairs.drug_class,
        pairs.failure_category,
        denominators.findings_in_class,
        per_month.findings_in_month

)

select * from final
