package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * The auth endpoints and the filter chain over real HTTP.
 *
 * <p>What is protected matters as much as what works: the default here is deny, so an endpoint
 * added later is closed until somebody opens it deliberately.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
@Import(TestDatabase.class)
// Both: the gold fixture because one test calls a public data endpoint, and the delete so each
// test starts with no accounts. Loading gold here rather than relying on another test class
// having loaded it is what keeps this independent of test order - the container is shared.
@Sql("classpath:db/gold-fixture.sql")
@Sql(statements = "DELETE FROM app.users", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
class AuthHttpTest {

    @Autowired
    RestTestClient client;

    @MockitoBean
    JavaMailSender mail;

    private void register(String email, String password) {
        client.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"%s\",\"password\":\"%s\"}".formatted(email, password))
                .exchange()
                .expectStatus()
                .isAccepted();
    }

    private String loginAndGetAccessToken(String email, String password) {
        var body = client.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"%s\",\"password\":\"%s\"}".formatted(email, password))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return body.replaceAll(".*\"accessToken\"\\s*:\\s*\"([^\"]+)\".*", "$1");
    }

    // ------------------------------------------------------------------ the public surface

    @Test
    void the_public_data_needs_no_account() {
        // This is a public-interest site. The batch checker must work for somebody who will never
        // register, and that is a product decision the filter chain has to reflect.
        client.get().uri("/api/v1/alerts/latest").exchange().expectStatus().isOk();
    }

    @Test
    void registering_answers_the_same_whether_or_not_the_address_is_taken() {
        // The response bytes are compared, not just the status: a different message would be the
        // same oracle in a different coat.
        register("reader@example.com", "a-long-enough-password");

        var first = client.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"taken-later@example.com\",\"password\":\"a-long-enough-password\"}")
                .exchange()
                .expectStatus()
                .isAccepted()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        var second = client.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"reader@example.com\",\"password\":\"a-long-enough-password\"}")
                .exchange()
                .expectStatus()
                .isAccepted()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(second).isEqualTo(first);
    }

    @Test
    void a_short_password_is_refused() {
        client.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"reader@example.com\",\"password\":\"short\"}")
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody()
                .jsonPath("$.detail.password")
                .exists();
    }

    @Test
    void something_that_is_not_an_email_is_refused() {
        client.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"not-an-email\",\"password\":\"a-long-enough-password\"}")
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    // ------------------------------------------------------------------ login and tokens

    @Test
    void logging_in_returns_a_usable_token() {
        register("reader@example.com", "a-long-enough-password");

        assertThat(loginAndGetAccessToken("reader@example.com", "a-long-enough-password"))
                .isNotBlank()
                .contains("."); // a JWT has three dot-separated parts
    }

    @Test
    void the_wrong_password_is_a_401_that_says_nothing_useful() {
        register("reader@example.com", "a-long-enough-password");

        client.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"reader@example.com\",\"password\":\"wrong-password-here\"}")
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody()
                .jsonPath("$.error")
                .isEqualTo("Email or password is not correct");
    }

    @Test
    void an_unknown_address_fails_with_the_identical_message() {
        client.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"nobody@example.com\",\"password\":\"a-long-enough-password\"}")
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody()
                .jsonPath("$.error")
                .isEqualTo("Email or password is not correct");
    }

    @Test
    void a_password_never_appears_in_a_response() {
        register("reader@example.com", "a-long-enough-password");

        var body = client.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"reader@example.com\",\"password\":\"a-long-enough-password\"}")
                .exchange()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(body).doesNotContain("a-long-enough-password").doesNotContain("passwordHash");
    }

    // ------------------------------------------------------------------ what is protected

    @Test
    void an_authenticated_endpoint_refuses_an_anonymous_caller() {
        // /api/v1/watchlist is built in step 4. It is already protected, because the filter chain
        // denies by default - which is the property being checked here, not the endpoint.
        client.get().uri("/api/v1/watchlist").exchange().expectStatus().isUnauthorized();
    }

    @Test
    void an_invented_token_is_refused() {
        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer not.a.real.token")
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void a_token_signed_with_the_wrong_key_is_refused() {
        // The signature is the whole point: without verification anybody could write their own
        // "subject" claim and become any user.
        String forged = "eyJhbGciOiJIUzI1NiJ9"
                + ".eyJzdWIiOiIxIiwic2NvcGUiOiJST0xFX0FETUlOIn0"
                + ".aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + forged)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void a_real_token_reaches_a_protected_endpoint() {
        register("reader@example.com", "a-long-enough-password");
        String token = loginAndGetAccessToken("reader@example.com", "a-long-enough-password");

        // Step 4 has not built the watchlist yet, so the endpoint does not exist - but the point
        // is that the request gets past authentication: 404, not 401.
        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isNotFound();
    }
}
