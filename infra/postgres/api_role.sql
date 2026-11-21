-- The Postgres role the Spring Boot API uses: SELECT on `gold`, full rights on its own `app`
-- schema, and nothing else.
--
-- Two different privileges, on purpose, because the API plays two different parts:
--
--   * Against the **warehouse** it is a reader. The gold layer is dbt's output and the API has no
--     business editing it; a stray `UPDATE gold.fact_nsq_sample` is the kind of bug that silently
--     rewrites published CDSCO findings. Written as a grant, "the API reads gold" becomes
--     something the database enforces rather than something the code promises.
--   * Against its **own tables** - accounts, the watchlist, sent notifications, refresh tokens -
--     it is the owner. Those live in a separate `app` schema that Flyway migrates and dbt never
--     touches, so neither tool can surprise the other.
--
-- It also limits what a compromise of the public API is worth: this role cannot read `staging`
-- (silver before its quality gate), cannot read `ops` (the pipeline run log), cannot write
-- anything in `gold`, and cannot reach the `airflow`, `superset` or `mlflow` databases at all.
--
-- Idempotent: safe to re-run after `docker compose down -v`.
--
-- Run (password comes from the environment, never from this file):
--   docker compose exec -T postgres psql -U drugwatch -v ON_ERROR_STOP=1 \
--     -v api_password="$API_DB_PASSWORD" -f - < infra/postgres/api_role.sql

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

GRANT CONNECT ON DATABASE drugwatch TO drugwatch_api;

-- --------------------------------------------------------------------------- the warehouse: read
GRANT USAGE ON SCHEMA gold TO drugwatch_api;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO drugwatch_api;

-- dbt drops and recreates gold tables on every build, and a new table carries no grants. Without
-- this the API would lose access to a mart the next time the pipeline ran - which would surface
-- as the batch checker returning nothing, at the worst possible moment.
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO drugwatch_api;

-- --------------------------------------------------------------------------- its own tables: own
-- Created here rather than by Flyway so that ownership is unambiguous: the role owns the schema,
-- so every table Flyway creates inside it is owned by the role too.
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION drugwatch_api;
GRANT ALL ON SCHEMA app TO drugwatch_api;

-- --------------------------------------------------------------------------- everything else: no
-- Said explicitly rather than relied upon. `staging` holds silver before the quality gate and
-- `ops` holds the pipeline run log; neither is public data, and the API is the public service.
REVOKE ALL ON SCHEMA staging, ops, dbt_staging, dbt_intermediate FROM drugwatch_api;
REVOKE ALL ON ALL TABLES IN SCHEMA staging, ops FROM drugwatch_api;
REVOKE CREATE ON SCHEMA gold FROM drugwatch_api;
REVOKE ALL ON SCHEMA public FROM drugwatch_api;

-- --------------------------------------------------------------------------- what it can do now
SELECT
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'gold' AND c.relkind = 'r'
        AND has_table_privilege('drugwatch_api', c.oid, 'SELECT')) AS gold_tables_readable,
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'gold' AND c.relkind = 'r'
        AND has_table_privilege('drugwatch_api', c.oid, 'UPDATE')) AS gold_tables_writable,
    has_schema_privilege('drugwatch_api', 'app', 'CREATE') AS can_create_in_app,
    has_schema_privilege('drugwatch_api', 'staging', 'USAGE') AS can_see_staging,
    has_schema_privilege('drugwatch_api', 'ops', 'USAGE') AS can_see_ops;
