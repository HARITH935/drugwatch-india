-- The Neon equivalent of api_role.sql (Phase 12, ADR 0021): same role, same two privileges
-- (SELECT on `gold`, own the `app` schema), created on the production database instead of the
-- local one.
--
-- Two things differ from the local script, both because of what publish_gold.sh actually copies:
--
--   * Neon's database is NOT guaranteed to be named "drugwatch" - Neon names the first database
--     it gives you whatever you (or its UI) chose when the project was created. So instead of
--     hardcoding a name, this grants CONNECT on whichever database the connection string already
--     landed us in (current_database()).
--   * publish_gold.sh only ever copies the `gold` schema (--schema=gold). `staging`, `ops`,
--     `dbt_staging` and `dbt_intermediate` are never created on Neon at all, so the local script's
--     "REVOKE ALL ... FROM drugwatch_api" on those schemas would fail here with "schema does not
--     exist" - there is nothing to revoke, because production never has anything beyond gold,
--     public and this role's own app schema in the first place.
--
-- Idempotent: safe to re-run (e.g. after rotating API_DB_PASSWORD, or after a second
-- publish_gold.sh run drops and recreates gold).
--
-- Run from the repo root, with NEON_DATABASE_URL and API_DB_PASSWORD in .env (borrows the local
-- postgres container's psql client - the Mac has none of its own, same reasoning as
-- publish_gold.sh):
--   set -a && . ./.env && set +a
--   docker compose exec -T postgres psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -v api_password="$API_DB_PASSWORD" -f - < infra/postgres/neon_api_role.sql

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'drugwatch_api') THEN
        CREATE ROLE drugwatch_api LOGIN;
        RAISE NOTICE 'created role drugwatch_api';
    ELSE
        RAISE NOTICE 'role drugwatch_api already exists';
    END IF;
END
$$;

-- Set on every run, so rotating the password is just re-running this file.
ALTER ROLE drugwatch_api WITH PASSWORD :'api_password';

-- current_database(), not a hardcoded name: see header.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO drugwatch_api', current_database());
END
$$;

-- --------------------------------------------------------------------------- the warehouse: read
GRANT USAGE ON SCHEMA gold TO drugwatch_api;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO drugwatch_api;

-- publish_gold.sh's --clean drops and recreates every gold table on each run, and a recreated
-- table carries no grants. Without this, the API would lose access to a mart the next time
-- gold was republished - which would surface as the batch checker returning nothing, in
-- production, at the worst possible moment.
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO drugwatch_api;

-- --------------------------------------------------------------------------- its own tables: own
-- Unlike the local superuser, Neon's connecting role is not automatically a member of a role it
-- just created, so it cannot hand that role ownership of a schema until it can "become" it too.
DO $$
BEGIN
    EXECUTE format('GRANT drugwatch_api TO %I', current_user);
END
$$;

-- Same as local: created here so ownership is unambiguous, then Flyway (running from Render)
-- creates its tables inside a schema it already owns.
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION drugwatch_api;
GRANT ALL ON SCHEMA app TO drugwatch_api;

-- --------------------------------------------------------------------------- everything else: no
-- Only `public` needs saying here - see header for why staging/ops/dbt_* don't apply on Neon.
REVOKE CREATE ON SCHEMA gold FROM drugwatch_api;
REVOKE ALL ON SCHEMA public FROM drugwatch_api;

-- --------------------------------------------------------------------------- what it can do now
SELECT
    current_database() AS database,
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'gold' AND c.relkind = 'r'
        AND has_table_privilege('drugwatch_api', c.oid, 'SELECT')) AS gold_tables_readable,
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'gold' AND c.relkind = 'r'
        AND has_table_privilege('drugwatch_api', c.oid, 'UPDATE')) AS gold_tables_writable,
    has_schema_privilege('drugwatch_api', 'app', 'CREATE') AS can_create_in_app;
