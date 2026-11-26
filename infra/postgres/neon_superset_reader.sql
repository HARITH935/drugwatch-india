-- The Neon equivalent of superset_reader.sql (Phase 12, ADR 0021): same role, same single
-- privilege (SELECT on `gold`), created on the production database the Phase 12 Superset Space
-- will connect to instead of the local one.
--
-- Differs from the local script the same way neon_api_role.sql does, for the same reason:
--   * CONNECT is granted on current_database(), not a hardcoded "drugwatch" - Neon's database
--     name is whatever was chosen when the project was created.
--   * No REVOKE on staging/ops/dbt_staging/dbt_intermediate: publish_gold.sh (--schema=gold)
--     never creates them on Neon, so there is nothing there to revoke.
--
-- Idempotent: safe to re-run (e.g. after rotating SUPERSET_READER_PASSWORD, or after a second
-- publish_gold.sh run drops and recreates gold).
--
-- Run from the repo root, with NEON_DATABASE_URL and SUPERSET_READER_PASSWORD in .env:
--   set -a && . ./.env && set +a
--   docker compose exec -T postgres psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -v reader_password="$SUPERSET_READER_PASSWORD" -f - < infra/postgres/neon_superset_reader.sql

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

-- current_database(), not a hardcoded name: see header.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO superset_reader', current_database());
END
$$;

GRANT USAGE ON SCHEMA gold TO superset_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO superset_reader;

-- publish_gold.sh's --clean drops and recreates every gold table on each run, and a recreated
-- table carries no grants. Without this, the Space's dashboards would go blank the next time
-- gold was republished.
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO superset_reader;

-- Said explicitly rather than relied on: nothing outside gold, no writes anywhere. (Only
-- `public` needs saying - see header for why staging/ops/dbt_* don't apply on Neon.)
REVOKE CREATE ON SCHEMA gold FROM superset_reader;
REVOKE ALL ON SCHEMA public FROM superset_reader;

SELECT current_database() AS database,
       count(*) FILTER (WHERE has_table_privilege('superset_reader', c.oid, 'SELECT')) AS gold_tables_readable
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'gold' AND c.relkind = 'r';
