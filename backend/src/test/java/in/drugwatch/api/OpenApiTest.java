package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.shared.PublicNotes;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * The published OpenAPI document.
 *
 * <p>These are not tests of springdoc. They are tests of the three things about the document that
 * are this project's decisions rather than the library's: that every endpoint is described, that
 * the caveats CLAUDE.md section 6 requires are on it, and that it is readable without a token
 * while saying which endpoints need one.
 *
 * <p>The "every operation has a summary" test is the one with teeth. Adding an endpoint and not
 * documenting it is the normal way an API document rots, and it rots silently - the page still
 * loads, it is just less true than it looks. Here it fails the build instead.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
@Import({TestDatabase.class, TestRedis.class})
class OpenApiTest {

    /** Plan §10's endpoint list. Kept here as a literal, so a disappearing endpoint fails too. */
    private static final List<String> EXPECTED_PATHS = List.of(
            "/api/v1/batches/search",
            "/api/v1/drugs/{id}",
            "/api/v1/drugs/search",
            "/api/v1/manufacturers/{id}",
            "/api/v1/manufacturers/{id}/risk",
            "/api/v1/alerts/latest",
            "/api/v1/auth/register",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/logout",
            "/api/v1/auth/verify",
            "/api/v1/watchlist",
            "/api/v1/watchlist/{id}",
            "/api/v1/dashboards",
            "/api/v1/dashboards/{key}/guest-token");

    @Autowired
    RestTestClient client;

    @SuppressWarnings("unchecked")
    private Map<String, Object> document() {
        var body = client.get()
                .uri("/v3/api-docs")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(Map.class)
                .returnResult()
                .getResponseBody();
        return (Map<String, Object>) body;
    }

    @Test
    void the_document_is_readable_without_a_token() {
        // The API is public, so a description of it leaks nothing. Locking the document would only
        // mean nobody finds out how to call the endpoints that are already open.
        assertThat(document()).containsKey("openapi");
    }

    @Test
    void it_is_an_openapi_3_1_document() {
        assertThat(document().get("openapi").toString()).startsWith("3.1");
    }

    @Test
    @SuppressWarnings("unchecked")
    void every_endpoint_in_the_plan_is_described() {
        var paths = (Map<String, Object>) document().get("paths");

        assertThat(paths).containsKeys(EXPECTED_PATHS.toArray(String[]::new));
    }

    @Test
    @SuppressWarnings("unchecked")
    void every_operation_has_a_summary_and_a_tag() {
        var paths = (Map<String, Object>) document().get("paths");
        var undocumented = new ArrayList<String>();

        paths.forEach((path, byMethod) -> ((Map<String, Object>) byMethod).forEach((method, raw) -> {
            var operation = (Map<String, Object>) raw;
            if (operation.get("summary") == null || operation.get("tags") == null) {
                undocumented.add(method.toUpperCase() + " " + path);
            }
        }));

        assertThat(undocumented)
                .as("endpoints published with no summary or no tag - document them in the controller")
                .isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    void the_document_carries_the_disclaimer_and_what_the_data_does_not_say() {
        var info = (Map<String, Object>) document().get("info");
        var description = info.get("description").toString();

        // CLAUDE.md §6: this page is a page. Somebody may find the API before the website.
        assertThat(description).contains(PublicNotes.DISCLAIMER);
        assertThat(description).contains("one specific batch");
        assertThat(description).contains("not a guarantee of safety");
        assertThat(description).contains("reporting history");
    }

    @Test
    @SuppressWarnings("unchecked")
    void the_bearer_token_is_declared_but_not_demanded_of_the_public_endpoints() {
        var document = document();
        var schemes = (Map<String, Object>) ((Map<String, Object>) document.get("components")).get("securitySchemes");
        assertThat(schemes).containsKey("bearer-token");

        // A global security requirement would label the batch checker as needing an account, which
        // is the opposite of what this API is for.
        assertThat(document).doesNotContainKey("security");

        var paths = (Map<String, Object>) document.get("paths");
        var batchSearch = (Map<String, Object>) paths.get("/api/v1/batches/search");
        assertThat((Map<String, Object>) batchSearch.get("get")).doesNotContainKey("security");
    }

    @Test
    @SuppressWarnings("unchecked")
    void the_watchlist_says_it_needs_a_token() {
        var paths = (Map<String, Object>) document().get("paths");
        var watchlist = (Map<String, Object>) paths.get("/api/v1/watchlist");

        assertThat((Map<String, Object>) watchlist.get("get")).containsKey("security");
        assertThat((Map<String, Object>) watchlist.get("post")).containsKey("security");
    }

    @Test
    @SuppressWarnings("unchecked")
    void the_actuator_is_not_published_as_public_api() {
        // /actuator/health exists for Docker's healthcheck, not for clients to build on.
        var paths = (Map<String, Object>) document().get("paths");

        assertThat(paths.keySet()).noneMatch(path -> path.startsWith("/actuator"));
    }

    @Test
    void the_validation_rules_are_part_of_the_document() {
        // The minimum medicine-name length is a real rule, not a formality: a two-character name
        // plus a short batch number would produce a confident-looking coincidence. A client should
        // be able to read that rule rather than discover it from a 400.
        client.get()
                .uri("/v3/api-docs")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.paths['/api/v1/batches/search'].get.parameters[0].schema.minLength")
                .isEqualTo(3);
    }

    @Test
    void the_swagger_page_is_reachable_without_a_token() {
        // The path redirects to swagger-ui/index.html; either answer proves it is not behind auth.
        var status =
                client.get().uri("/swagger-ui.html").exchange().returnResult().getStatus();

        assertThat(status.is2xxSuccessful() || status.is3xxRedirection())
                .as("GET /swagger-ui.html returned %s", status)
                .isTrue();
    }
}
