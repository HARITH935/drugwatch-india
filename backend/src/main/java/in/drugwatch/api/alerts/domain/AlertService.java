package in.drugwatch.api.alerts.domain;

import in.drugwatch.api.shared.PublicNotes;
import java.sql.ResultSet;
import java.util.List;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * The latest alert month (plan §10's {@code /api/v1/alerts/latest}).
 *
 * <p>The number of findings in a month is reported beside <b>how many laboratories reported
 * them</b>, and that pairing is not decoration. Phase 6 measured the two at r = 0.964 across
 * years: a month with more findings is usually a month with more testing. Showing the first
 * number alone invites "medicine quality is getting worse", which the archive does not support.
 */
@Service
public class AlertService {

    private final JdbcClient jdbc;

    AlertService(DataSource dataSource) {
        this.jdbc = JdbcClient.create(dataSource);
    }

    public LatestAlerts latest() {
        String month = jdbc.sql("SELECT max(alert_month) FROM gold.fact_nsq_sample")
                .query(String.class)
                .optional()
                .orElse(null);
        if (month == null) {
            return new LatestAlerts(null, 0, 0, 0, List.of(), REPORTING_NOTE, PublicNotes.DISCLAIMER);
        }

        var summary = jdbc.sql("""
                        SELECT count(*) AS findings,
                               count(DISTINCT reported_by) AS reporting_labs,
                               count(DISTINCT manufacturer_id) AS companies
                        FROM gold.fact_nsq_sample WHERE alert_month = :month
                        """)
                .param("month", month)
                .query((ResultSet row, int number) ->
                        new long[] {row.getLong("findings"), row.getLong("reporting_labs"), row.getLong("companies")})
                .single();

        var medicines = jdbc.sql("""
                        SELECT d.product_name, count(*) AS findings
                        FROM gold.fact_nsq_sample f
                        JOIN gold.dim_drug d ON d.drug_id = f.drug_id
                        WHERE f.alert_month = :month
                        GROUP BY d.product_name
                        ORDER BY count(*) DESC, d.product_name
                        LIMIT 10
                        """)
                .param("month", month)
                .query((ResultSet row, int number) ->
                        new ReportedMedicine(row.getString("product_name"), row.getLong("findings")))
                .list();

        return new LatestAlerts(
                month, summary[0], summary[1], summary[2], medicines, REPORTING_NOTE, PublicNotes.DISCLAIMER);
    }

    private static final String REPORTING_NOTE =
            "The number of batches reported moves with the number of laboratories reporting them -"
                    + " across years the two track each other almost exactly. A busier month usually"
                    + " means more testing, not worse medicine.";

    public record ReportedMedicine(String productName, long findings) {}

    public record LatestAlerts(
            String alertMonth,
            long findings,
            long reportingLabs,
            long companies,
            List<ReportedMedicine> mostReportedMedicines,
            String note,
            String disclaimer) {}
}
