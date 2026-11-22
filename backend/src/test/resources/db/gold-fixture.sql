-- A miniature gold layer for the API's tests.
--
-- **Every row here is invented.** ADR 0003 keeps real CDSCO findings out of git, and a test
-- fixture is still git. The names are deliberately fictional - "Zyntophil", "Marvex Labs" - so
-- that nobody can mistake a test expectation for a published claim about a real medicine or a
-- real Indian company.
--
-- The shapes, though, are real, because they are what the tests need to be about:
--   * batch numbers with punctuation (KA/018) and without,
--   * the "Not applicable" sentinel that appears on 22 real findings,
--   * short numeric batch numbers that collide across manufacturers,
--   * a spurious finding, which carries NO manufacturer_id and names the copied brand instead.
--
-- gold is dbt's; this file only mirrors the columns the API reads. `GoldContractTest` checks
-- those columns still exist in the real warehouse, so this fixture cannot drift quietly.

CREATE SCHEMA IF NOT EXISTS gold;

-- Dropped first, so the file can run before every test method: each test then starts from the
-- same rows regardless of what the previous one did. A fixture that is only loadable once makes
-- tests depend on their order, which is the hardest kind of flake to find later.
DROP TABLE IF EXISTS gold.fact_nsq_sample CASCADE;
DROP TABLE IF EXISTS gold.dim_drug CASCADE;
DROP TABLE IF EXISTS gold.dim_manufacturer CASCADE;
DROP TABLE IF EXISTS gold.mart_ml_features CASCADE;

CREATE TABLE gold.dim_drug (
    drug_id      text PRIMARY KEY,
    product_name text,
    generic_name text,
    brand_name   text,
    dosage_form  text,
    strengths    text[],
    drug_classes text[]
);

CREATE TABLE gold.dim_manufacturer (
    manufacturer_id    text PRIMARY KEY,
    canonical_name     text,
    state_name         text,
    first_alert_month  text,
    last_alert_month   text,
    name_variant_count bigint
);

CREATE TABLE gold.fact_nsq_sample (
    sample_id           text PRIMARY KEY,
    drug_id             text,
    manufacturer_id     text,
    batch_no            text,
    alert_month         text,
    alert_month_start   date,
    failure_reason      text,
    failure_categories  text[],
    is_spurious         boolean,
    name_on_pack        text,
    reported_by         text,
    lab_type            text,
    reported_state_name text,
    source_url          text
);

INSERT INTO gold.dim_drug (drug_id, product_name, generic_name, dosage_form, strengths, drug_classes) VALUES
    ('d1', 'Zyntophil Tablets IP 40 mg', 'Zyntophil Tablets IP', 'Tablet', ARRAY['40 mg'], ARRAY['Antihypertensive / cardiovascular']),
    ('d2', 'Zyntophil Tab. 40mg',        'Zyntophil Tablets IP', 'Tablet', ARRAY['40 mg'], ARRAY['Antihypertensive / cardiovascular']),
    ('d3', 'Brivolax Oral Suspension',   NULL,                   'Suspension', ARRAY['100 mg/5 ml'], ARRAY['Antibiotic']),
    ('d4', 'Calmirex Cough Syrup',       NULL,                   'Syrup', ARRAY[]::text[], ARRAY[]::text[]);

INSERT INTO gold.dim_manufacturer (manufacturer_id, canonical_name, state_name, first_alert_month, last_alert_month, name_variant_count) VALUES
    ('m1', 'Marvex Laboratories Private Limited', 'Himachal Pradesh', '2024-01', '2026-03', 3),
    ('m2', 'Ostrella Pharma Limited',             'Gujarat',          '2025-06', '2025-06', 1),
    -- A company in the archive with no feature row at all: the risk proxy must say "not
    -- scoreable" rather than invent a number.
    ('m2-no-features', 'Verdane Formulations Limited', 'Kerala',       '2026-01', '2026-01', 1);

INSERT INTO gold.fact_nsq_sample
    (sample_id, drug_id, manufacturer_id, batch_no, alert_month, alert_month_start, failure_reason,
     failure_categories, is_spurious, name_on_pack, reported_by, lab_type, reported_state_name, source_url) VALUES
    -- Punctuated batch number: a user typing KA018 must find this.
    ('s1', 'd1', 'm1', 'KA/018', '2026-03', DATE '2026-03-01', 'Dissolution',
     ARRAY['Dissolution'], false, NULL, 'CDL Kolkata', 'Central', 'West Bengal', 'https://example.invalid/alert/2026-03.pdf'),
    -- Same batch number, a DIFFERENT medicine: this is a "close match", not a match.
    ('s2', 'd3', 'm2', 'KA-018', '2025-06', DATE '2025-06-01', 'Assay',
     ARRAY['Assay'], false, NULL, 'DTL Ahmedabad', 'State', 'Gujarat', 'https://example.invalid/alert/2025-06.pdf'),
    -- The sentinel. 22 real findings carry "Not applicable" as the batch number.
    ('s3', 'd4', 'm1', 'Not applicable', '2025-01', DATE '2025-01-01', 'Description',
     ARRAY['Description'], false, NULL, 'CDTL Mumbai', 'Central', 'Maharashtra', 'https://example.invalid/alert/2025-01.pdf'),
    -- A spurious finding: no manufacturer_id at all, and the copied brand in name_on_pack.
    ('s4', 'd1', NULL, 'SPU-77', '2026-02', DATE '2026-02-01', 'Spurious',
     ARRAY['Spurious'], true, 'Zyntophil', 'CDL Kolkata', 'Central', 'West Bengal', 'https://example.invalid/alert/2026-02.pdf'),
    -- A second finding for the same medicine, so "multiple findings" is exercised.
    ('s5', 'd2', 'm1', 'KA 018', '2025-11', DATE '2025-11-01', 'Assay and Dissolution',
     ARRAY['Assay','Dissolution'], false, NULL, 'DTL Shimla', 'State', 'Himachal Pradesh', 'https://example.invalid/alert/2025-11.pdf');

-- The feature table the risk proxy reads. Only the columns it uses, with invented values: the
-- point of these rows is the shape (a null share, a company with history before the training
-- cutoff and one without), not the numbers.
CREATE TABLE gold.mart_ml_features (
    manufacturer_id               text,
    as_of_month                   text,
    reports_3m                    numeric,
    reports_6m                    numeric,
    reports_12m                   numeric,
    reports_24m                   numeric,
    reports_prior_6m              numeric,
    reports_trend_6m              numeric,
    months_since_last_report      numeric,
    distinct_drugs_12m            numeric,
    distinct_reporting_states_12m numeric,
    central_lab_reports_12m       numeric,
    state_lab_reports_12m         numeric,
    central_lab_share_12m         numeric,
    category_mentions_12m         numeric,
    assay_share_12m               numeric,
    dissolution_share_12m         numeric,
    sterility_share_12m           numeric,
    description_share_12m         numeric,
    class_mentions_12m            numeric,
    distinct_drug_classes_12m     numeric,
    antibiotic_share_12m          numeric,
    analgesic_share_12m           numeric,
    gastrointestinal_share_12m    numeric,
    vitamin_share_12m             numeric,
    respiratory_share_12m         numeric,
    cardiovascular_share_12m      numeric,
    antihistamine_share_12m       numeric,
    unclassified_share_12m        numeric,
    share_of_archive_reports_12m  numeric
);

-- m1: history from before the training cutoff (2024-10), so the model has seen it. The newest
-- row is 2026-03, which is the scoring case - features known, outcome not yet knowable.
INSERT INTO gold.mart_ml_features (manufacturer_id, as_of_month, reports_12m, reports_24m, months_since_last_report, assay_share_12m)
VALUES ('m1', '2024-06', 2, 3, 1, 0.5),
       ('m1', '2026-03', 3, 5, 0, 0.3);

-- m2: first appears after the cutoff, so it belongs to the group the model is weakest on - and
-- its assay share is NULL, which is a real value (no findings in the window to divide), not zero.
INSERT INTO gold.mart_ml_features (manufacturer_id, as_of_month, reports_12m, reports_24m, months_since_last_report, assay_share_12m)
VALUES ('m2', '2025-06', 1, 1, 0, NULL);

