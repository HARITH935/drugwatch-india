package in.drugwatch.api.manufacturers.domain;

import in.drugwatch.api.config.CacheConfig;
import in.drugwatch.api.shared.NotFoundException;
import in.drugwatch.api.shared.PublicNotes;
import java.sql.ResultSet;
import java.util.List;
import java.util.Optional;
import javax.sql.DataSource;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * The manufacturer page (plan §4.4).
 *
 * <p>This is the page the project's ethics rules bear on hardest, because it is the one that names
 * a company. Three things follow:
 *
 * <ul>
 *   <li><b>Spurious findings cannot appear here at all.</b> Not by a filter - by the data: those
 *       rows carry no {@code manufacturer_id} in gold (Phase 4), so there is nothing to join. The
 *       company printed on a counterfeit pack is the brand that was copied.
 *   <li><b>The count is of reported batches, never of "failures by this company".</b> The wording
 *       is in the response, so a client cannot label the number something stronger.
 *   <li><b>How often the company appears is given next to how long it has been in the archive.</b>
 *       A company with 12 findings over 8 years and one with 12 in a single month read very
 *       differently, and a bare count hides the difference.
 * </ul>
 */
@Service
public class ManufacturerService {

    private final JdbcClient jdbc;

    ManufacturerService(DataSource dataSource) {
        this.jdbc = JdbcClient.create(dataSource);
    }

    @Cacheable(cacheNames = CacheConfig.MANUFACTURER_PAGES, keyGenerator = "dataVersionKeyGenerator")
    public ManufacturerPage page(String manufacturerId) {
        Manufacturer manufacturer = find(manufacturerId).orElseThrow(() -> new NotFoundException("No such company"));
        return new ManufacturerPage(
                manufacturer, medicinesFor(manufacturerId), REPORTED_BATCHES_MEANING, PublicNotes.DISCLAIMER);
    }

    private Optional<Manufacturer> find(String manufacturerId) {
        return jdbc.sql("""
                        SELECT m.manufacturer_id, m.canonical_name, m.state_name,
                               m.first_alert_month, m.last_alert_month,
                               count(f.sample_id) AS reported_batches,
                               count(DISTINCT f.alert_month) AS alert_months,
                               count(DISTINCT f.drug_id) AS distinct_medicines
                        FROM gold.dim_manufacturer m
                        LEFT JOIN gold.fact_nsq_sample f ON f.manufacturer_id = m.manufacturer_id
                        WHERE m.manufacturer_id = :id
                        GROUP BY m.manufacturer_id, m.canonical_name, m.state_name,
                                 m.first_alert_month, m.last_alert_month
                        """)
                .param("id", manufacturerId)
                .query((ResultSet row, int number) -> new Manufacturer(
                        row.getString("manufacturer_id"),
                        row.getString("canonical_name"),
                        row.getString("state_name"),
                        row.getString("first_alert_month"),
                        row.getString("last_alert_month"),
                        row.getLong("reported_batches"),
                        row.getLong("alert_months"),
                        row.getLong("distinct_medicines")))
                .optional();
    }

    private List<ReportedMedicine> medicinesFor(String manufacturerId) {
        return jdbc.sql("""
                        SELECT d.drug_id, d.product_name, count(*) AS reported_batches,
                               max(f.alert_month) AS last_alert_month
                        FROM gold.fact_nsq_sample f
                        JOIN gold.dim_drug d ON d.drug_id = f.drug_id
                        WHERE f.manufacturer_id = :id
                        GROUP BY d.drug_id, d.product_name
                        ORDER BY count(*) DESC, max(f.alert_month) DESC
                        LIMIT 100
                        """)
                .param("id", manufacturerId)
                .query((ResultSet row, int number) -> new ReportedMedicine(
                        row.getString("drug_id"),
                        row.getString("product_name"),
                        row.getLong("reported_batches"),
                        row.getString("last_alert_month")))
                .list();
    }

    private static final String REPORTED_BATCHES_MEANING =
            "These are batches of this company's medicines that a government laboratory reported."
                    + " Each finding is about one tested batch. Sampling is not random, so a larger"
                    + " number can mean more testing rather than more problems, and this is a record"
                    + " of reporting history rather than of quality.";

    /** A company as the archive knows it. */
    public record Manufacturer(
            String manufacturerId,
            String name,
            String state,
            String firstAlertMonth,
            String lastAlertMonth,
            long reportedBatches,
            long alertMonths,
            long distinctMedicines) {}

    /** One of its medicines, with how many of its batches have been reported. */
    public record ReportedMedicine(String drugId, String productName, long reportedBatches, String lastAlertMonth) {}

    /** The page. */
    public record ManufacturerPage(
            Manufacturer manufacturer, List<ReportedMedicine> medicines, String meaning, String disclaimer) {}
}
