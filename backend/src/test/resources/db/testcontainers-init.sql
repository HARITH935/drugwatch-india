-- Creates what infra/postgres/api_role.sql creates in the real database: the `app` schema that
-- Flyway migrates into. The production script also grants SELECT on `gold` and revokes everything
-- else, which is a privilege question rather than a schema question and is checked against the
-- real database instead (ApiRolePrivilegesTest).
CREATE SCHEMA IF NOT EXISTS app;
