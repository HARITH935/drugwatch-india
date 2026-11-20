-- Every share in mart_ml_features must be a share, and none may be silently always-zero.
--
-- The second half is the point. While adding the drug-class features I wrote
-- `filter (where drug_class = 'Unclassified')`, which counted **zero of 1,382 unclassified
-- findings** - because `dim_drug.drug_classes` holds an EMPTY ARRAY when the vocabulary matched
-- nothing, deliberately, rather than the string 'Unclassified' (ADR 0014). The column built fine,
-- every row passed every range check, and the feature was a constant 0. Nothing failed.
--
-- A column that is always zero is the worst kind of broken feature: the model trains on it
-- without complaint, SHAP reports it as unimportant (which is true and useless), and the mistake
-- looks exactly like "this signal does not help". So each share is checked for being a share AND
-- for actually varying.

with shares as (

    select * from {{ ref('mart_ml_features') }}

),

out_of_range as (

    select 'share outside 0..1' as problem, as_of_month, manufacturer_id
    from shares
    where share_of_archive_reports_12m not between 0 and 1
       or antibiotic_share_12m not between 0 and 1
       or analgesic_share_12m not between 0 and 1
       or gastrointestinal_share_12m not between 0 and 1
       or vitamin_share_12m not between 0 and 1
       or respiratory_share_12m not between 0 and 1
       or cardiovascular_share_12m not between 0 and 1
       or antihistamine_share_12m not between 0 and 1
       or unclassified_share_12m not between 0 and 1
       or assay_share_12m not between 0 and 1
       or dissolution_share_12m not between 0 and 1
       or sterility_share_12m not between 0 and 1
       or description_share_12m not between 0 and 1
       or central_lab_share_12m not between 0 and 1

),

-- A share must be null exactly when there is nothing to divide. Null where findings exist, or a
-- number where none do, both mean the window join went wrong.
null_mismatch as (

    select 'share null state disagrees with the window' as problem, as_of_month, manufacturer_id
    from shares
    -- coalesce is required, not tidiness: the mention counts are NULL (not 0) when the window
    -- holds no findings, and `NULL > 0` is NULL, which `is distinct from false` reports as TRUE.
    -- Written without it, this branch flagged all 46,296 quiet rows as broken data.
    where (coalesce(class_mentions_12m, 0) > 0) is distinct from (antibiotic_share_12m is not null)
       or (coalesce(category_mentions_12m, 0) > 0) is distinct from (assay_share_12m is not null)

),

-- The constant-zero check. Each of these is a real slice of the archive, so a feature that never
-- once rises above zero is not a weak signal, it is a bug.
always_zero as (

    select 'feature is constant zero across every row' as problem, null as as_of_month, name
    from (
        select 'antibiotic_share_12m' as name, max(antibiotic_share_12m) as peak from shares
        union all select 'analgesic_share_12m', max(analgesic_share_12m) from shares
        union all select 'gastrointestinal_share_12m', max(gastrointestinal_share_12m) from shares
        union all select 'vitamin_share_12m', max(vitamin_share_12m) from shares
        union all select 'respiratory_share_12m', max(respiratory_share_12m) from shares
        union all select 'cardiovascular_share_12m', max(cardiovascular_share_12m) from shares
        union all select 'antihistamine_share_12m', max(antihistamine_share_12m) from shares
        union all select 'unclassified_share_12m', max(unclassified_share_12m) from shares
        union all select 'distinct_drug_classes_12m', max(distinct_drug_classes_12m) from shares
        union all select 'share_of_archive_reports_12m', max(share_of_archive_reports_12m) from shares
    ) as peaks
    where peak is null or peak = 0

)

select * from out_of_range
union all select * from null_mismatch
union all select * from always_zero
