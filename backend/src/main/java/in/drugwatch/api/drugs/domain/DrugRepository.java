package in.drugwatch.api.drugs.domain;

import in.drugwatch.api.batches.domain.Finding;
import java.sql.Array;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Optional;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Drug lookup and search over the gold layer.
 *
 * <p>Search uses {@code pg_trgm} similarity (Phase 9 decision B), which is what lets "telmisartan"
 * find "Telmisartan Tablets IP 40 mg" and survive a typo. dbt builds the trigram index as a
 * post-hook, because it drops and recreates every mart on each run and an index added by hand
 * would quietly disappear the next month.
 *
 * <p>Note what search does <b>not</b> do: it does not merge differently-printed names into one
 * medicine. Phase 4 measured that and left them separate, because deciding that "Paracetamol
 * Tablets IP 500 mg" and "Paracetamol Tab. 500mg" are the same product needs the same kind of
 * reviewed evidence the manufacturer merge needed.
 */
@Repository
public class DrugRepository {

    private static final String DRUG_WITH_COUNTS = """
            SELECT d.drug_id, d.product_name, d.generic_name, d.dosage_form, d.strengths, d.drug_classes,
                   count(f.sample_id) AS findings,
                   min(f.alert_month) AS first_alert_month,
                   max(f.alert_month) AS last_alert_month
            FROM gold.dim_drug d
            LEFT JOIN gold.fact_nsq_sample f ON f.drug_id = d.drug_id
            """;

    private final JdbcClient jdbc;

    DrugRepository(DataSource dataSource) {
        this.jdbc = JdbcClient.create(dataSource);
    }

    public Optional<DrugSummary> findById(String drugId) {
        return jdbc.sql(DRUG_WITH_COUNTS + " WHERE d.drug_id = :id GROUP BY d.drug_id, d.product_name,"
                        + " d.generic_name, d.dosage_form, d.strengths, d.drug_classes")
                .param("id", drugId)
                .query(DrugRepository::toSummary)
                .optional();
    }

    /** Findings for one medicine, newest alert first. */
    public List<Finding> findingsFor(String drugId) {
        return jdbc.sql("""
                        SELECT f.batch_no, f.alert_month, d.product_name, f.failure_reason,
                               f.failure_categories, f.is_spurious, f.name_on_pack,
                               f.manufacturer_id, m.canonical_name AS manufacturer_name,
                               f.reported_by, f.lab_type, f.source_url
                        FROM gold.fact_nsq_sample f
                        JOIN gold.dim_drug d ON d.drug_id = f.drug_id
                        LEFT JOIN gold.dim_manufacturer m ON m.manufacturer_id = f.manufacturer_id
                        WHERE f.drug_id = :id
                        ORDER BY f.alert_month DESC
                        LIMIT 200
                        """)
                .param("id", drugId)
                .query(DrugRepository::toFinding)
                .list();
    }

    /**
     * Fuzzy name search. {@code %} is pg_trgm's similarity operator; the threshold is Postgres's
     * default (0.3), which a measured run showed tolerates a transposed letter.
     */
    public List<DrugSummary> search(String text, int limit) {
        return jdbc.sql(DRUG_WITH_COUNTS
                        // `%` is pg_trgm's similarity operator, not a wildcard, and needs no escaping here.
                        // The ILIKE beside it catches substrings that trigram similarity scores
                        // below the threshold - "Zynto" against a long product name.
                        + " WHERE d.product_name % :text OR d.product_name ILIKE '%' || :text || '%'"
                        + " GROUP BY d.drug_id, d.product_name, d.generic_name, d.dosage_form,"
                        + " d.strengths, d.drug_classes"
                        + " ORDER BY similarity(d.product_name, :text) DESC, count(f.sample_id) DESC"
                        + " LIMIT :limit")
                .param("text", text)
                .param("limit", limit)
                .query(DrugRepository::toSummary)
                .list();
    }

    private static DrugSummary toSummary(ResultSet row, int rowNumber) throws SQLException {
        return new DrugSummary(
                row.getString("drug_id"),
                row.getString("product_name"),
                row.getString("generic_name"),
                row.getString("dosage_form"),
                toList(row.getArray("strengths")),
                toList(row.getArray("drug_classes")),
                row.getLong("findings"),
                row.getString("first_alert_month"),
                row.getString("last_alert_month"));
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
                spurious ? null : row.getString("manufacturer_id"),
                spurious ? null : row.getString("manufacturer_name"),
                row.getString("reported_by"),
                row.getString("lab_type"),
                row.getString("source_url"));
    }

    private static List<String> toList(Array array) throws SQLException {
        return array == null ? List.of() : List.of((String[]) array.getArray());
    }
}
