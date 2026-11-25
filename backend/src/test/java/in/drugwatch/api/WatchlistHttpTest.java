package in.drugwatch.api;

import in.drugwatch.api.watchlist.domain.WatchlistNotifier;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * The watchlist over HTTP, including who is allowed to see whose watches.
 *
 * <p>The ownership test is the important one: the user id comes from the verified token, never
 * from the request, so there is no parameter to tamper with.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
@Sql(statements = "DELETE FROM app.users", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
class WatchlistHttpTest {

    @Autowired
    RestTestClient client;

    @Autowired
    WatchlistNotifier notifier;

    @Autowired
    DataSource dataSource;

    @MockitoBean
    JavaMailSender mail;

    private String tokenFor(String email) {
        client.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"%s\",\"password\":\"a-long-enough-password\"}".formatted(email))
                .exchange()
                .expectStatus()
                .isAccepted();
        String body = client.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"email\":\"%s\",\"password\":\"a-long-enough-password\"}".formatted(email))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return body.replaceAll(".*\"accessToken\"\\s*:\\s*\"([^\"]+)\".*", "$1");
    }

    private Long addWatch(String token, String term) {
        String body = client.post()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"term\":\"%s\"}".formatted(term))
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return Long.valueOf(body.replaceAll(".*\"id\"\\s*:\\s*(\\d+).*", "$1"));
    }

    @Test
    void a_watch_can_be_added_listed_and_removed() {
        String token = tokenFor("reader@example.com");

        Long id = addWatch(token, "Zyntophil");

        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.watches[0].term")
                .isEqualTo("Zyntophil")
                .jsonPath("$.note")
                .exists();

        client.delete()
                .uri("/api/v1/watchlist/" + id)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isNoContent();

        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectBody()
                .jsonPath("$.watches")
                .isEmpty();
    }

    @Test
    void a_watch_reports_when_it_was_added() {
        // Regression: the column is database-defaulted, and with insertable=false the saved
        // object never learned the value - so the API answered "createdAt": null for a field it
        // advertises.
        String token = tokenFor("reader@example.com");
        addWatch(token, "Zyntophil");

        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectBody()
                .jsonPath("$.watches[0].createdAt")
                .exists();
    }

    @Test
    void the_watchlist_needs_a_token() {
        client.get().uri("/api/v1/watchlist").exchange().expectStatus().isUnauthorized();
    }

    @Test
    void one_user_cannot_see_another_users_watches() {
        String first = tokenFor("a@example.com");
        String second = tokenFor("b@example.com");
        addWatch(first, "Zyntophil");

        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + second)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.watches")
                .isEmpty();
    }

    @Test
    void one_user_cannot_delete_another_users_watch() {
        // There is no user id in the request to tamper with - it comes from the signed token - so
        // the only thing an attacker controls is the watch id, and that is scoped by owner.
        String owner = tokenFor("owner@example.com");
        String other = tokenFor("other@example.com");
        Long id = addWatch(owner, "Zyntophil");

        client.delete()
                .uri("/api/v1/watchlist/" + id)
                .header("Authorization", "Bearer " + other)
                .exchange()
                .expectStatus()
                .isNotFound();

        client.get()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + owner)
                .exchange()
                .expectBody()
                .jsonPath("$.watches[0].term")
                .isEqualTo("Zyntophil");
    }

    @Test
    void notification_history_is_empty_until_something_is_actually_sent() {
        String token = tokenFor("reader@example.com");
        addWatch(token, "Zyntophil");

        client.get()
                .uri("/api/v1/watchlist/notifications")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.notifications")
                .isEmpty()
                .jsonPath("$.note")
                .exists();
    }

    @Test
    void a_sent_notification_shows_up_in_its_recipients_history() {
        String token = tokenFor("reader@example.com");
        Long id = addWatch(token, "Zyntophil");
        // Same trick as WatchlistTest's backdate(): pretend the watch predates the archive so its
        // matches become notifiable, then actually run the notifier rather than insert the row by
        // hand - this test is only trustworthy if it goes through the real send path. The notifier
        // only ever mails a verified address (decision E), and tokenFor() never calls /verify, so
        // that has to be set here too, or runOnce() below sends nothing and the real finding here
        // would be "the test account wasn't verified", not anything about this endpoint.
        JdbcClient.create(dataSource)
                .sql("UPDATE app.watchlist_items SET since_alert_month = '2025-01' WHERE id = ?")
                .param(id)
                .update();
        JdbcClient.create(dataSource)
                .sql("UPDATE app.users SET email_verified = true WHERE email = 'reader@example.com'")
                .update();
        notifier.runOnce();

        client.get()
                .uri("/api/v1/watchlist/notifications")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.notifications[0].term")
                .isEqualTo("Zyntophil")
                .jsonPath("$.notifications[0].alertMonth")
                .exists()
                .jsonPath("$.notifications[0].findingsMatched")
                .isNumber();
    }

    @Test
    void the_notifications_endpoint_needs_a_token_too() {
        client.get()
                .uri("/api/v1/watchlist/notifications")
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void a_term_that_cannot_be_matched_is_a_400_with_the_reason() {
        String token = tokenFor("reader@example.com");

        client.post()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"term\":\"ab\"}")
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    void the_same_term_twice_is_a_400_not_a_second_row() {
        String token = tokenFor("reader@example.com");
        addWatch(token, "Zyntophil");

        client.post()
                .uri("/api/v1/watchlist")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"term\":\"zyntophil\"}")
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody()
                .jsonPath("$.error")
                .isEqualTo("You are already watching that.");
    }
}
