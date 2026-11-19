-- The Postgres role Superset uses to read the warehouse: SELECT on `gold`, and nothing else.
--
-- CLAUDE.md §5 says Superset reads gold only. Written as a grant rather than a convention, that
-- sentence becomes something the database enforces: a chart built against `staging.silver_nsq` or
-- `ops.pipeline_run` fails with "permission denied" instead of quietly publishing data that was
-- never meant to be public - the operational run log, or silver before its quality gate.
--
-- It also limits what a Superset compromise is worth. Superset is the one service that will be
-- exposed to the internet (Phase 12), and this role cannot write a row, read the `airflow` or
-- `superset` databases, or see any schema but `gold`.
--
-- Idempotent: safe to re-run after `docker compose down -v`.
--
-- Run (password comes from the environment, never from this file):
--   docker compose exec -T postgres psql -U drugwatch -v ON_ERROR_STOP=1 \
--     -v reader_password="$SUPERSET_READER_PASSWORD" -f - < infra/postgres/superset_reader.sql

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_reader') THEN
        CREATE ROLE superset_reader LOGIN;
        RAISE NOTICE 'created role superset_reader';
    ELSE
        RAISE NOTICE 'role superset_reader already exists';
    END IF;
END
$$;

-- Set on every run, so rotating the password is just re-running this file.
ALTER ROLE superset_reader WITH PASSWORD :'reader_password';

-- Connect to the warehouse database, and see one schema in it.
GRANT CONNECT ON DATABASE drugwatch TO superset_reader;
GRANT USAGE ON SCHEMA gold TO superset_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO superset_reader;

-- dbt drops and recreates gold tables on every build, and a new table carries no grants. Without
-- this, Superset would lose access to a mart the next time the pipeline ran - the kind of break
-- that shows up as an empty dashboard at the worst moment.
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO superset_reader;

-- Said explicitly rather than relied on: nothing outside gold, and no writes anywhere.
REVOKE ALL ON SCHEMA staging, ops, dbt_staging, dbt_intermediate FROM superset_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA staging, ops FROM superset_reader;
REVOKE CREATE ON SCHEMA gold FROM superset_reader;

SELECT 'superset_reader can read:' AS check,
       count(*) FILTER (WHERE has_table_privilege('superset_reader', c.oid, 'SELECT')) AS gold_tables_readable
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'gold' AND c.relkind = 'r';
