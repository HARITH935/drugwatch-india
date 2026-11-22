package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.risk.domain.RiskService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;

/**
 * The risk proxy against the real Phase 8 service.
 *
 * <p>This is the test that would catch the feature set drifting apart. The proxy sends 28 named
 * features and the service refuses a request that is missing any (ADR 0017), so if Phase 7 ever
 * adds a feature and this list is not updated, the call fails here rather than silently falling
 * back to "score unavailable" in production - which looks identical to the service being down.
 *
 * <p>Needs the service running, so it skips without {@code API_DB_PASSWORD}, the same marker the
 * other live tests use.
 */
@SpringBootTest
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
@TestPropertySource(properties = "drugwatch.risk.base-url=http://localhost:8000")
@EnabledIfEnvironmentVariable(
        named = "API_DB_PASSWORD",
        matches = ".+",
        disabledReason = "needs the risk-api container running on :8000")
class RiskProxyLiveTest {

    @Autowired
    RiskService risk;

    @Test
    void a_company_the_model_has_seen_gets_a_score_and_an_explanation() {
        var result = risk.scoreFor("m1");

        assertThat(result.available())
                .as("the risk service on :8000 should have answered; is the container running?")
                .isTrue();
        assertThat(result.score()).isBetween(0.0, 1.0);
        assertThat(result.explanation()).isNotEmpty();
        // The approved wording from Phase 7's vocabulary, served through two services.
        assertThat(String.join(" ", result.explanation())).contains("not the quality");
    }

    @Test
    void the_feature_set_this_proxy_sends_is_the_one_the_model_expects() {
        // If this fails with available=false while the container is up, the 28-feature list in
        // RiskService has drifted from the model's and the service returned 422.
        assertThat(risk.scoreFor("m1").available()).isTrue();
    }

    @Test
    void the_client_speaks_a_protocol_the_model_service_understands() {
        // Regression, and the hardest bug in this phase to see. Java's HttpClient defaults to
        // offering an HTTP/2 upgrade and sends the body chunked; uvicorn answers that with
        // 422 "body: Field required" - headers arrive, body does not. The fallback then reported
        // "no score today", which is identical to the service being down, so in production this
        // would have been a permanently missing score with nothing logged as an error.
        //
        // If the HTTP/1.1 pin is ever removed, this fails instead of going quiet.
        assertThat(risk.scoreFor("m1").available())
                .as("a 422 here means the request body did not survive the HTTP protocol negotiation")
                .isTrue();
    }

    @Test
    void a_company_the_model_never_trained_on_is_told_so() {
        // The model card's largest limitation - PR-AUC 0.269 against 0.438 - said to the reader
        // it applies to, rather than averaged away.
        var result = risk.scoreFor("m2");

        assertThat(result.available()).isTrue();
        assertThat(result.modelHasSeenThisCompany()).isFalse();
        assertThat(result.accuracyNote()).contains("considerably less accurate");
    }

    @Test
    void a_company_with_history_before_the_cutoff_is_marked_as_seen() {
        var result = risk.scoreFor("m1");

        assertThat(result.modelHasSeenThisCompany()).isTrue();
        assertThat(result.accuracyNote()).contains("predicts best");
    }

    @Test
    void the_models_own_limitations_travel_with_the_score() {
        // Phase 7 put them on the registered model version; Phase 8 serves them from /health and
        // /explain; this carries them to the reader. Three services, one sentence.
        var result = risk.scoreFor("m1");

        assertThat(result.meaning()).contains("reporting history");
        assertThat(result.meaning()).contains("logistic regression");
    }
}
