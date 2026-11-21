package in.drugwatch.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * The endpoints over real HTTP: what they answer, and what they refuse.
 *
 * <p>The refusals are the point. A public lookup that quietly accepts a two-character medicine
 * name answers a different question from the one asked, and an error that echoes a SQL message
 * hands an attacker the schema.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
class PublicApiHttpTest {

    @Autowired
    RestTestClient client;

    @Test
    void the_batch_checker_answers_over_http() {
        client.get()
                .uri("/api/v1/batches/search?drug=Zyntophil&batch=KA018")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.outcome")
                .isEqualTo("FLAGGED")
                .jsonPath("$.findings[0].sourceUrl")
                .exists()
                .jsonPath("$.disclaimer")
                .isEqualTo("Not medical advice. Data from CDSCO public alerts.");
    }

    @Test
    void a_missing_parameter_says_which_one() {
        client.get()
                .uri("/api/v1/batches/search?drug=Zyntophil")
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody()
                .jsonPath("$.detail.parameter")
                .isEqualTo("batch");
    }

    @Test
    void a_medicine_name_too_short_to_mean_anything_is_refused() {
        // Two characters match most of the archive; combined with a short batch number that
        // produces a confident-looking match built on a coincidence.
        client.get()
                .uri("/api/v1/batches/search?drug=Zy&batch=KA018")
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody()
                .jsonPath("$.detail.drug")
                .exists();
    }

    @Test
    void even_an_error_carries_the_disclaimer() {
        // A client that only ever renders the error path still shows it.
        client.get()
                .uri("/api/v1/batches/search?drug=Zy&batch=KA018")
                .exchange()
                .expectBody()
                .jsonPath("$.disclaimer")
                .isEqualTo("Not medical advice. Data from CDSCO public alerts.");
    }

    @Test
    void an_unknown_medicine_is_a_404_and_not_a_stack_trace() {
        client.get()
                .uri("/api/v1/drugs/does-not-exist")
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody()
                .jsonPath("$.error")
                .isEqualTo("No such medicine");
    }

    @Test
    void an_error_response_names_no_internals() {
        // No SQL, no class names, no framework version: that is free reconnaissance.
        client.get()
                .uri("/api/v1/drugs/search?q=ab")
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody(String.class)
                .consumeWith(response -> {
                    String body = response.getResponseBody();
                    org.assertj.core.api.Assertions.assertThat(body)
                            .doesNotContain("SELECT")
                            .doesNotContain("org.springframework")
                            .doesNotContain("PSQLException")
                            .doesNotContain("gold.");
                });
    }

    @Test
    void the_drug_search_endpoint_answers() {
        client.get()
                .uri("/api/v1/drugs/search?q=Zyntophil")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.matches[0].productName")
                .exists()
                .jsonPath("$.note")
                .exists();
    }

    @Test
    void the_manufacturer_endpoint_answers() {
        client.get()
                .uri("/api/v1/manufacturers/m1")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.manufacturer.name")
                .isEqualTo("Marvex Laboratories Private Limited")
                .jsonPath("$.meaning")
                .exists();
    }

    @Test
    void the_latest_alerts_endpoint_answers() {
        client.get()
                .uri("/api/v1/alerts/latest")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.alertMonth")
                .isEqualTo("2026-03")
                .jsonPath("$.reportingLabs")
                .exists();
    }

    @Test
    void an_unknown_path_is_a_404_not_a_500() {
        // Regression. A catch-all @ExceptionHandler(Exception.class) swallows Spring's own
        // status-carrying exceptions, so every unknown path started answering "500, quote this
        // reference". That hides real errors, and tells anyone probing for paths that the one
        // they guessed did something.
        client.get()
                .uri("/api/v1/there-is-no-such-thing")
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody()
                .jsonPath("$.error")
                .isEqualTo("No such endpoint");
    }

    @Test
    void a_limit_beyond_what_is_allowed_is_refused_rather_than_clamped() {
        // Silently clamping would let a caller believe they had asked for 5,000 and received all
        // of them.
        client.get()
                .uri("/api/v1/drugs/search?q=Zyntophil&limit=5000")
                .exchange()
                .expectStatus()
                .isBadRequest();
    }
}
