package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * What the {@code drugwatch_api} role may actually do, asked of the real database.
 *
 * <p>{@code infra/postgres/api_role.sql} claims the API can read {@code gold}, owns {@code app},
 * and can touch nothing else. That claim is the project's main defence against a compromise of
 * the one public service, and until something tries the forbidden thing it is only a comment in a
 * SQL file.
 *
 * <p>Testcontainers cannot answer this: its container has one superuser and none of the grants.
 * So this runs against the developer's own Postgres and skips when {@code API_DB_PASSWORD} is
 * absent - the same shape as the Python integration tests, which skip without
 * {@code POSTGRES_PASSWORD}.
 */
@EnabledIfEnvironmentVariable(
        named = "API_DB_PASSWORD",
        matches = ".+",
        disabledReason = "needs the local Postgres with infra/postgres/api_role.sql applied")
class ApiRolePrivilegesTest {

    private Connection asApiRole() throws SQLException {
        String host = System.getenv().getOrDefault("POSTGRES_HOST", "localhost");
        String port = System.getenv().getOrDefault("POSTGRES_PORT", "5433");
        String database = System.getenv().getOrDefault("POSTGRES_DB", "drugwatch");
        return DriverManager.getConnection(
                "jdbc:postgresql://%s:%s/%s".formatted(host, port, database),
                System.getenv().getOrDefault("API_DB_USER", "drugwatch_api"),
                System.getenv("API_DB_PASSWORD"));
    }

    @Test
    void it_can_read_the_gold_layer() throws SQLException {
        try (Connection connection = asApiRole();
                Statement statement = connection.createStatement();
                ResultSet rows = statement.executeQuery("SELECT count(*) FROM gold.fact_nsq_sample")) {
            rows.next();
            assertThat(rows.getInt(1)).isPositive();
        }
    }

    @Test
    void it_cannot_write_to_the_gold_layer() throws SQLException {
        // The one that matters. gold is dbt's output and these are published CDSCO findings; a
        // stray UPDATE from the public API would silently rewrite them.
        try (Connection connection = asApiRole();
                Statement statement = connection.createStatement()) {
            assertThatThrownBy(() -> statement.executeUpdate("UPDATE gold.fact_nsq_sample SET batch_no = 'x'"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("permission denied");
        }
    }

    @Test
    void it_cannot_create_tables_in_the_gold_layer() throws SQLException {
        try (Connection connection = asApiRole();
                Statement statement = connection.createStatement()) {
            assertThatThrownBy(() -> statement.executeUpdate("CREATE TABLE gold.sneaky (x int)"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("permission denied");
        }
    }

    @Test
    void it_cannot_read_silver_before_the_quality_gate() throws SQLException {
        // staging holds silver as loaded, before Great Expectations has passed on it. The public
        // API must never be able to serve that.
        try (Connection connection = asApiRole();
                Statement statement = connection.createStatement()) {
            assertThatThrownBy(() -> statement.executeQuery("SELECT 1 FROM staging.silver_nsq"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("permission denied");
        }
    }

    @Test
    void it_cannot_read_the_pipeline_run_log() throws SQLException {
        // ops holds Phase 5's operational history: what ran, what failed, how long it took. That
        // is internal detail, and the dashboards get the one curated row through a dbt mart.
        try (Connection connection = asApiRole();
                Statement statement = connection.createStatement()) {
            assertThatThrownBy(() -> statement.executeQuery("SELECT 1 FROM ops.pipeline_run"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("permission denied");
        }
    }

    @Test
    void it_owns_its_own_schema() throws SQLException {
        try (Connection connection = asApiRole();
                Statement statement = connection.createStatement()) {
            statement.executeUpdate("CREATE TABLE app.privilege_probe (x int)");
            statement.executeUpdate("DROP TABLE app.privilege_probe");
        }
    }
}
