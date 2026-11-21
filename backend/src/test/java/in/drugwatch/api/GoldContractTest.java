package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.batches.domain.BatchNumber;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * What the API assumes about the real warehouse, checked against the real warehouse.
 *
 * <p>Two different risks, both invisible until a user hits them:
 *
 * <ol>
 *   <li><b>The test fixture drifts from gold.</b> {@code db/gold-fixture.sql} invents its rows
 *       (ADR 0003), so every other test would keep passing after dbt renamed a column. This asks
 *       the real warehouse whether the columns still exist.
 *   <li><b>The two batch normalisations drift apart.</b> The rule lives in Java ({@link
 *       BatchNumber}) and again in SQL ({@code FindingRepository}), because the query has to
 *       normalise 7,126 stored values and the request has to normalise one typed value. If they
 *       disagree the user is simply told their medicine is not in the archive - no error, no log
 *       line. So both are run over every batch number CDSCO has published and required to agree.
 * </ol>
 *
 * <p>Skips without {@code API_DB_PASSWORD}, like the privilege tests: CI has no warehouse.
 */
@EnabledIfEnvironmentVariable(
        named = "API_DB_PASSWORD",
        matches = ".+",
        disabledReason = "needs the local Postgres with the gold layer built")
class GoldContractTest {

    private Connection warehouse() throws SQLException {
        String host = System.getenv().getOrDefault("POSTGRES_HOST", "localhost");
        String port = System.getenv().getOrDefault("POSTGRES_PORT", "5433");
        String database = System.getenv().getOrDefault("POSTGRES_DB", "drugwatch");
        return DriverManager.getConnection(
                "jdbc:postgresql://%s:%s/%s".formatted(host, port, database),
                System.getenv().getOrDefault("API_DB_USER", "drugwatch_api"),
                System.getenv("API_DB_PASSWORD"));
    }

    @Test
    void every_column_the_api_reads_still_exists() throws SQLException {
        var required = java.util.Map.of(
                "fact_nsq_sample",
                List.of(
                        "sample_id",
                        "drug_id",
                        "manufacturer_id",
                        "batch_no",
                        "alert_month",
                        "alert_month_start",
                        "failure_reason",
                        "failure_categories",
                        "is_spurious",
                        "name_on_pack",
                        "reported_by",
                        "lab_type",
                        "reported_state_name",
                        "source_url"),
                "dim_drug",
                List.of("drug_id", "product_name", "generic_name", "dosage_form", "strengths", "drug_classes"),
                "dim_manufacturer",
                List.of("manufacturer_id", "canonical_name", "state_name", "first_alert_month", "last_alert_month"));

        try (Connection connection = warehouse()) {
            for (var table : required.entrySet()) {
                List<String> present = new ArrayList<>();
                try (var statement = connection.prepareStatement("SELECT column_name FROM information_schema.columns"
                        + " WHERE table_schema = 'gold' AND table_name = ?")) {
                    statement.setString(1, table.getKey());
                    try (ResultSet rows = statement.executeQuery()) {
                        while (rows.next()) {
                            present.add(rows.getString(1));
                        }
                    }
                }
                assertThat(present)
                        .as("gold.%s changed shape; the API and its test fixture are built on it", table.getKey())
                        .containsAll(table.getValue());
            }
        }
    }

    @Test
    void the_java_and_sql_batch_normalisations_agree_on_every_published_batch_number() throws SQLException {
        List<String> disagreements = new ArrayList<>();
        int checked = 0;

        try (Connection connection = warehouse();
                Statement statement = connection.createStatement();
                ResultSet rows = statement.executeQuery("SELECT DISTINCT batch_no,"
                        + " upper(regexp_replace(batch_no, '[^A-Za-z0-9]', '', 'g')) AS normalised"
                        + " FROM gold.fact_nsq_sample WHERE batch_no IS NOT NULL")) {
            while (rows.next()) {
                checked++;
                String printed = rows.getString("batch_no");
                String fromSql = rows.getString("normalised");
                // Java additionally refuses sentinels and very short values, which SQL does not
                // need to: the query only ever runs for a value Java already accepted. So the
                // comparison is on the characters, for the values Java considers searchable.
                var fromJava = BatchNumber.normalise(printed);
                if (fromJava.isPresent() && !fromJava.get().equals(fromSql.toUpperCase(Locale.ROOT))) {
                    disagreements.add("%s -> java=%s sql=%s".formatted(printed, fromJava.get(), fromSql));
                }
            }
        }

        assertThat(checked)
                .as("the archive should contain batch numbers to check")
                .isGreaterThan(1000);
        assertThat(disagreements)
                .as("the Java and SQL batch normalisations must produce identical text")
                .isEmpty();
    }

    @Test
    void the_sentinel_this_code_refuses_is_really_in_the_archive() throws SQLException {
        // If "Not applicable" ever stopped appearing, the refusal would be dead code protecting
        // against nothing - worth knowing rather than carrying forever on faith.
        try (Connection connection = warehouse();
                Statement statement = connection.createStatement();
                ResultSet rows = statement.executeQuery("SELECT count(*) FROM gold.fact_nsq_sample"
                        + " WHERE upper(regexp_replace(batch_no, '[^A-Za-z0-9]', '', 'g')) = 'NOTAPPLICABLE'")) {
            rows.next();
            assertThat(rows.getInt(1)).as("the sentinel BatchNumber refuses").isPositive();
        }
    }
}
