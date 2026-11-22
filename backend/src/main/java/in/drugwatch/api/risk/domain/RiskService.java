package in.drugwatch.api.risk.domain;

import in.drugwatch.api.shared.NotFoundException;
import in.drugwatch.api.shared.PublicNotes;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * The manufacturer risk score (plan §4.3, §10).
 *
 * <p>This endpoint carries more caveats than any other in the API, and they are not decoration -
 * they are what {@code docs/model-card.md} measured:
 *
 * <ul>
 *   <li><b>It is reporting history, not quality.</b> Sampling is not random; a company tested
 *       often has more chances to appear, and one never sampled cannot appear at all.
 *   <li><b>It is no better than a linear model.</b> On the held-out test window the difference was
 *       +0.011 PR-AUC with a confidence interval of -0.004 to +0.026, which includes zero. The
 *       score is published because it is the plan's deliverable and the explanations are useful,
 *       not because the algorithm earned it.
 *   <li><b>It is much weaker for companies the model never trained on</b> - PR-AUC 0.269 against
 *       0.438. 48% of the companies in the test window were in that group, so the API says which
 *       side a given company falls on rather than averaging over the difference.
 *   <li><b>It under-predicts.</b> Training months averaged 12.8% positive and the test period
 *       16.0%, so the number is systematically a little low.
 * </ul>
 *
 * <p>The features come from {@code gold.mart_ml_features}, whose <b>newest</b> row for a company
 * is exactly the scoring case: features known now, outcome not knowable yet. Phase 7 kept those
 * rows out of training for that reason and available for this one.
 */
@Service
public class RiskService {

    /**
     * The last cutoff the production model trained on (Phase 7 step 1's embargo). A company with
     * no feature row at or before this month was never seen in training, which is the difference
     * between PR-AUC 0.438 and 0.269.
     */
    private static final String TRAINING_ENDED = "2024-10";

    /**
     * The 28 features the model expects, in no particular order - the service matches by name and
     * refuses a request that is missing any (ADR 0017), so a drift here fails loudly rather than
     * scoring on a shifted matrix.
     */
    private static final List<String> FEATURES = List.of(
            "reports_3m",
            "reports_6m",
            "reports_12m",
            "reports_24m",
            "reports_prior_6m",
            "reports_trend_6m",
            "months_since_last_report",
            "distinct_drugs_12m",
            "distinct_reporting_states_12m",
            "central_lab_reports_12m",
            "state_lab_reports_12m",
            "central_lab_share_12m",
            "category_mentions_12m",
            "assay_share_12m",
            "dissolution_share_12m",
            "sterility_share_12m",
            "description_share_12m",
            "class_mentions_12m",
            "distinct_drug_classes_12m",
            "antibiotic_share_12m",
            "analgesic_share_12m",
            "gastrointestinal_share_12m",
            "vitamin_share_12m",
            "respiratory_share_12m",
            "cardiovascular_share_12m",
            "antihistamine_share_12m",
            "unclassified_share_12m",
            "share_of_archive_reports_12m");

    private final JdbcClient jdbc;
    private final RiskClient riskService;

    RiskService(DataSource dataSource, RiskClient riskService) {
        this.jdbc = JdbcClient.create(dataSource);
        this.riskService = riskService;
    }

    public RiskResult scoreFor(String manufacturerId) {
        String name = jdbc.sql("SELECT canonical_name FROM gold.dim_manufacturer WHERE manufacturer_id = :id")
                .param("id", manufacturerId)
                .query(String.class)
                .optional()
                .orElseThrow(() -> new NotFoundException("No such company"));

        Optional<FeatureRow> features = latestFeatures(manufacturerId);
        if (features.isEmpty()) {
            // A company with no feature row has never been reported, so the model has nothing to
            // work from. Saying so is the honest answer; a score of zero would read as "safe".
            return RiskResult.notScoreable(
                    manufacturerId,
                    name,
                    "This company has no reported findings in the archive, so there is no history to"
                            + " base a score on. That is not a statement about its medicines.");
        }

        FeatureRow row = features.get();
        boolean seenInTraining = wasSeenInTraining(manufacturerId);

        return riskService
                .explain(row.values())
                .map(explanation -> RiskResult.scored(
                        manufacturerId,
                        name,
                        explanation.score(),
                        row.asOfMonth(),
                        seenInTraining,
                        explanation.explanation(),
                        explanation.limitations()))
                .orElseGet(() -> RiskResult.unavailable(manufacturerId, name, row.asOfMonth()));
    }

    private Optional<FeatureRow> latestFeatures(String manufacturerId) {
        String columns = String.join(", ", FEATURES);
        // The newest row, label knowable or not: that is the scoring case by design.
        String sql = "SELECT as_of_month, " + columns // noqa - column names are the constant above
                + " FROM gold.mart_ml_features WHERE manufacturer_id = :id"
                + " ORDER BY as_of_month DESC LIMIT 1";
        return jdbc.sql(sql)
                .param("id", manufacturerId)
                .query(RiskService::toFeatureRow)
                .optional();
    }

    /** Did this company have any feature row at or before the training cutoff? */
    private boolean wasSeenInTraining(String manufacturerId) {
        return jdbc.sql("""
                        SELECT EXISTS (
                            SELECT 1 FROM gold.mart_ml_features
                            WHERE manufacturer_id = :id AND as_of_month <= :cutoff)
                        """)
                .param("id", manufacturerId)
                .param("cutoff", TRAINING_ENDED)
                .query(Boolean.class)
                .single();
    }

    private static FeatureRow toFeatureRow(ResultSet row, int number) throws SQLException {
        Map<String, Double> values = new LinkedHashMap<>();
        for (String feature : FEATURES) {
            double value = row.getDouble(feature);
            // A SQL NULL reads as 0.0 from getDouble, and null is a real value here - a share is
            // null when the window held no findings to divide. The model was trained to read the
            // difference, so it must be preserved rather than flattened to zero.
            values.put(feature, row.wasNull() ? null : value);
        }
        return new FeatureRow(row.getString("as_of_month"), values);
    }

    private record FeatureRow(String asOfMonth, Map<String, Double> values) {}

    /** What the endpoint answers, in all three cases. */
    public record RiskResult(
            String manufacturerId,
            String name,
            Boolean available,
            Double score,
            String featuresAsOfMonth,
            Boolean modelHasSeenThisCompany,
            List<String> explanation,
            String accuracyNote,
            String meaning,
            String disclaimer) {

        static RiskResult scored(
                String id,
                String name,
                double score,
                String asOfMonth,
                boolean seenInTraining,
                List<String> explanation,
                String limitations) {
            return new RiskResult(
                    id,
                    name,
                    true,
                    score,
                    asOfMonth,
                    seenInTraining,
                    explanation,
                    seenInTraining ? SEEN_IN_TRAINING : NEW_TO_THE_MODEL,
                    MEANING + " " + limitations,
                    PublicNotes.DISCLAIMER);
        }

        static RiskResult unavailable(String id, String name, String asOfMonth) {
            return new RiskResult(
                    id,
                    name,
                    false,
                    null,
                    asOfMonth,
                    null,
                    List.of(),
                    null,
                    "The risk score is temporarily unavailable. Everything else on this page comes"
                            + " from CDSCO's published alerts and is unaffected.",
                    PublicNotes.DISCLAIMER);
        }

        static RiskResult notScoreable(String id, String name, String why) {
            return new RiskResult(id, name, false, null, null, null, List.of(), null, why, PublicNotes.DISCLAIMER);
        }

        private static final String MEANING =
                "This estimates the chance that a batch from this company is named in a CDSCO alert"
                        + " in the next six months. It is built from how often batches have been"
                        + " reported before, so it reflects reporting history and testing attention,"
                        + " not the quality of the company's medicines.";

        private static final String SEEN_IN_TRAINING =
                "The model was trained on this company's earlier history, which is the group it" + " predicts best.";

        /** The model card's largest limitation, said to the reader it applies to. */
        private static final String NEW_TO_THE_MODEL =
                "This company's history begins after the model was trained, and the model is"
                        + " considerably less accurate for such companies. Treat this number with"
                        + " more caution than usual.";
    }
}
