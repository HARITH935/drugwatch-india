package in.drugwatch.api.batches.domain;

import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Reads findings out of the gold layer.
 *
 * <p>Plain SQL rather than JPA, deliberately. {@code gold} is dbt's output: it has no entity
 * graph to map, it is rebuilt every month, and the API's role cannot write to it anyway. An ORM
 * over it would add a mapping layer with nothing to map and would put a {@code save()} method
 * within reach of a published CDSCO finding.
 *
 * <p><b>The batch normalisation in this SQL must match {@link BatchNumber} exactly.</b> Two
 * implementations of one rule drift, and the drift here would be invisible - a user would simply
 * be told their medicine is not in the archive. {@code BatchNormalisationAgreementTest} runs both
 * over every batch number in the real archive and requires identical answers.
 */
@Repository
public class FindingRepository {

    /** Keep letters and digits, upper-case. The SQL half of {@link BatchNumber#normalise}. */
    private static final String NORMALISED_BATCH = "upper(regexp_replace(f.batch_no, '[^A-Za-z0-9]', '', 'g'))";

    private static final String SELECT_FINDING = """
            SELECT f.batch_no,
                   f.alert_month,
                   d.product_name,
                   f.failure_reason,
                   f.failure_categories,
                   f.is_spurious,
                   f.name_on_pack,
                   f.manufacturer_id,
                   m.canonical_name AS manufacturer_name,
                   f.reported_by,
                   f.lab_type,
                   f.source_url
            FROM gold.fact_nsq_sample f
            JOIN gold.dim_drug d ON d.drug_id = f.drug_id
            LEFT JOIN gold.dim_manufacturer m ON m.manufacturer_id = f.manufacturer_id
            """;

    private final JdbcClient jdbc;

    FindingRepository(DataSource dataSource) {
        this.jdbc = JdbcClient.create(dataSource);
    }

    /** Findings whose batch matches exactly and whose product name contains the search text. */
    public List<Finding> findByBatchAndDrug(String normalisedBatch, String drugText) {
        return jdbc.sql(SELECT_FINDING
                        + " WHERE " + NORMALISED_BATCH + " = :batch"
                        + " AND d.product_name ILIKE '%' || :drug || '%'"
                        + " ORDER BY f.alert_month DESC LIMIT 100")
                .param("batch", normalisedBatch)
                .param("drug", drugText)
                .query(FindingRepository::toFinding)
                .list();
    }

    /**
     * Findings with the same batch number but a product name that does not contain the search
     * text. §4.1's "close matches": the batch is in the archive, attached to a medicine the user
     * did not name - which is worth showing, and is not the same as a match.
     */
    public List<Finding> findByBatchOnly(String normalisedBatch, String excludedDrugText) {
        return jdbc.sql(SELECT_FINDING
                        + " WHERE " + NORMALISED_BATCH + " = :batch"
                        + " AND d.product_name NOT ILIKE '%' || :drug || '%'"
                        + " ORDER BY f.alert_month DESC LIMIT 20")
                .param("batch", normalisedBatch)
                .param("drug", excludedDrugText)
                .query(FindingRepository::toFinding)
                .list();
    }

    private static Finding toFinding(ResultSet row, int rowNumber) throws SQLException {
        boolean spurious = row.getBoolean("is_spurious");
        return new Finding(
                row.getString("batch_no"),
                row.getString("alert_month"),
                row.getString("product_name"),
                row.getString("failure_reason"),
                toList(row.getArray("failure_categories")),
                spurious,
                row.getString("name_on_pack"),
                // Belt and braces with the Finding constructor: a spurious row has no
                // manufacturer_id in gold, and nothing here may invent one.
                spurious ? null : row.getString("manufacturer_id"),
                spurious ? null : row.getString("manufacturer_name"),
                row.getString("reported_by"),
                row.getString("lab_type"),
                row.getString("source_url"));
    }

    private static List<String> toList(Array array) throws SQLException {
        if (array == null) {
            return List.of();
        }
        return List.of((String[]) array.getArray());
    }
}
