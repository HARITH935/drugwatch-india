package in.drugwatch.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.client.RestTestClient;

/** The guest-token endpoint over HTTP: what it accepts, refuses, and never caches. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
@Import({TestDatabase.class, TestRedis.class})
class GuestTokenHttpTest {

    @Autowired
    RestTestClient client;

    @Test
    void the_endpoint_is_public_because_the_dashboards_are() {
        // Plan §10 lists it as "Public (rate-limited)". 503 here means it got past the filter
        // chain and tried to reach Superset, which is unreachable in tests - not 401.
        client.post()
                .uri("/api/v1/dashboards/states/guest-token")
                .exchange()
                .expectStatus()
                .isEqualTo(503);
    }

    @Test
    void an_unlisted_dashboard_is_a_404() {
        client.post()
                .uri("/api/v1/dashboards/some-internal-dashboard/guest-token")
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody()
                .jsonPath("$.error")
                .isEqualTo("No such dashboard");
    }

    @Test
    void a_key_that_could_not_be_a_key_is_refused_before_the_lookup() {
        client.post()
                .uri("/api/v1/dashboards/Not_A_Valid_KEY/guest-token")
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    void the_token_endpoint_is_a_post_so_nothing_caches_a_credential() {
        // A GET would be cached by a browser, a proxy or a CDN, and a cached bearer token is a
        // token handed to whoever asks next.
        client.get()
                .uri("/api/v1/dashboards/states/guest-token")
                .exchange()
                .expectStatus()
                .isEqualTo(405);
    }

    @Test
    void the_available_list_is_public_and_names_only_keys() {
        client.get()
                .uri("/api/v1/dashboards")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.dashboards")
                .isArray()
                .jsonPath("$.dashboards[0]")
                .isEqualTo("drug-classes");
    }

    @Test
    void an_error_response_names_no_internals() {
        client.post()
                .uri("/api/v1/dashboards/states/guest-token")
                .exchange()
                .expectBody(String.class)
                .consumeWith(response -> org.assertj.core.api.Assertions.assertThat(response.getResponseBody())
                        .doesNotContainIgnoringCase("superset")
                        .doesNotContain("8088")
                        .doesNotContain("uuid"));
    }
}
