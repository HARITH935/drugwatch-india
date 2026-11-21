-- What the real database already has before the API starts, recreated for the test container:
--
--   * the `app` schema, which infra/postgres/api_role.sql creates and Flyway then migrates into;
--   * a miniature `gold`, which dbt owns in production and which the API only ever reads.
--
-- The production script also grants SELECT on gold and revokes everything else. That is a
-- privilege question rather than a schema question, and Testcontainers cannot answer it - its
-- container has one superuser and none of the grants - so it is checked against the real database
-- by ApiRolePrivilegesTest instead.
CREATE SCHEMA IF NOT EXISTS app;

-- The API's drug search uses pg_trgm similarity (Phase 9 decision B). In production dbt creates
-- the extension in an on-run-start hook, because CREATE EXTENSION needs rights the API's own role
-- does not have. The test container has a superuser, so it is created here - without it, every
-- search test fails with "operator does not exist: text % unknown" rather than a wrong answer.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
