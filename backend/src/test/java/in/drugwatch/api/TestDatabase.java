package in.drugwatch.api;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * A real Postgres for the tests, started once and shared by the whole suite.
 *
 * <p>Never H2. An in-memory database accepts SQL this project's Postgres rejects and rejects SQL
 * it accepts - array columns, partial indexes, {@code timestamptz}, the regex CHECK on
 * {@code alert_month} - so a passing test against H2 would say nothing about production.
 *
 * <p>The container is {@code static}, so one is started for the suite rather than one per test
 * class. Container startup is the dominant cost in a Java test suite that uses them, and the
 * difference is minutes.
 *
 * <p>{@code @ServiceConnection} wires the JDBC url, username and password into Spring by itself,
 * which also means the test configuration cannot drift from the container it is pointed at.
 */
@TestConfiguration(proxyBeanMethods = false)
class TestDatabase {

    @Bean
    @ServiceConnection
    static PostgreSQLContainer<?> postgres() {
        return new PostgreSQLContainer<>("postgres:17")
                // The migration targets a schema the role owns (infra/postgres/api_role.sql).
                // Here the container's own superuser runs it, so the schema is created up front.
                .withInitScript("db/testcontainers-init.sql");
    }
}
