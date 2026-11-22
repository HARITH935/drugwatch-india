package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * The rate limit over HTTP. The limit is set to 5 per minute for this class only.
 *
 * <p>What is <b>not</b> limited matters as much: the limiter must not sit in front of logging in
 * or the watchlist, where a shared office IP would lock out everybody after a few requests.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
@Import({TestDatabase.class, TestRedis.class})
@Sql("classpath:db/gold-fixture.sql")
// The limit is the subject here, so it is set low for this class only. Every other HTTP test
// shares the same Redis, and a low global limit would spend their budget too.
@org.springframework.test.context.TestPropertySource(properties = "drugwatch.rate-limit.per-minute=5")
class RateLimitHttpTest {

    @Autowired
    RestTestClient client;

    @Autowired
    StringRedisTemplate redis;

    @BeforeEach
    void clearCounters() {
        // Every test starts with a fresh window; otherwise the first test spends the budget for
        // all of them.
        redis.getConnectionFactory().getConnection().serverCommands().flushAll();
    }

    @Test
    void a_caller_within_the_limit_is_served() {
        client.get()
                .uri("/api/v1/alerts/latest")
                .exchange()
                .expectStatus()
                .isOk()
                .expectHeader()
                .exists("X-RateLimit-Remaining");
    }

    @Test
    void the_remaining_budget_counts_down() {
        String first = remainingAfterOneCall();
        String second = remainingAfterOneCall();

        // Sent on every response so a client can slow down on its own rather than being cut off.
        assertThat(Integer.parseInt(first)).isGreaterThan(Integer.parseInt(second));
    }

    @Test
    void a_caller_over_the_limit_gets_429_with_something_to_wait_for() {
        for (int i = 0; i < 5; i++) {
            client.get().uri("/api/v1/alerts/latest").exchange().expectStatus().isOk();
        }

        client.get()
                .uri("/api/v1/alerts/latest")
                .exchange()
                .expectStatus()
                .isEqualTo(429)
                .expectHeader()
                .exists("Retry-After")
                .expectBody()
                .jsonPath("$.detail.retryAfterSeconds")
                .exists()
                // Even at 429: a client that only renders the error path still shows it.
                .jsonPath("$.disclaimer")
                .isEqualTo("Not medical advice. Data from CDSCO public alerts.");
    }

    @Test
    void the_batch_checker_is_limited_too() {
        // It is the endpoint most worth protecting: one query per call against the whole archive.
        for (int i = 0; i < 5; i++) {
            client.get()
                    .uri("/api/v1/batches/search?drug=Zyntophil&batch=KA018")
                    .exchange()
                    .expectStatus()
                    .isOk();
        }

        client.get()
                .uri("/api/v1/batches/search?drug=Zyntophil&batch=KA018")
                .exchange()
                .expectStatus()
                .isEqualTo(429);
    }

    @Test
    void logging_in_is_not_rate_limited_by_ip() {
        // A shared office or college IP would otherwise lock everybody out of their account after
        // a handful of attempts. Brute-force protection belongs per-account, not per-address.
        for (int i = 0; i < 8; i++) {
            client.post()
                    .uri("/api/v1/auth/login")
                    .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                    .body("{\"email\":\"nobody@example.com\",\"password\":\"a-long-enough-password\"}")
                    .exchange()
                    .expectStatus()
                    .isUnauthorized();
        }
    }

    @Test
    void health_is_not_rate_limited() {
        // An orchestrator polls it every fifteen seconds; limiting it would make the service
        // report itself unhealthy under its own monitoring.
        for (int i = 0; i < 8; i++) {
            client.get().uri("/actuator/health").exchange().expectStatus().isOk();
        }
    }

    private String remainingAfterOneCall() {
        return client.get()
                .uri("/api/v1/alerts/latest")
                .exchange()
                .expectStatus()
                .isOk()
                .returnResult(String.class)
                .getResponseHeaders()
                .getFirst("X-RateLimit-Remaining");
    }
}
