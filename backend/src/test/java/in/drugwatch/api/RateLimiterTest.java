package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.shared.RateLimiter;
import java.time.Duration;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

/** The Redis request counter. */
@SpringBootTest
@Import({TestDatabase.class, TestRedis.class})
class RateLimiterTest {

    @Autowired
    RateLimiter limiter;

    /** A fresh bucket per test, so one test's counting cannot affect another's. */
    private String bucket() {
        return "test-" + UUID.randomUUID();
    }

    @Test
    void requests_within_the_limit_are_allowed_and_count_down() {
        String bucket = bucket();

        assertThat(limiter.check(bucket, 3, Duration.ofMinutes(1)).remaining()).isEqualTo(2);
        assertThat(limiter.check(bucket, 3, Duration.ofMinutes(1)).remaining()).isEqualTo(1);
        assertThat(limiter.check(bucket, 3, Duration.ofMinutes(1)).remaining()).isZero();
    }

    @Test
    void the_request_after_the_limit_is_refused() {
        String bucket = bucket();
        for (int i = 0; i < 3; i++) {
            assertThat(limiter.check(bucket, 3, Duration.ofMinutes(1)).allowed())
                    .isTrue();
        }

        var refused = limiter.check(bucket, 3, Duration.ofMinutes(1));

        assertThat(refused.allowed()).isFalse();
        assertThat(refused.remaining()).isZero();
        // Something to wait for, rather than "try again later".
        assertThat(refused.retryAfter()).isPositive();
    }

    @Test
    void each_caller_is_counted_separately() {
        String first = bucket();
        String second = bucket();
        for (int i = 0; i < 3; i++) {
            limiter.check(first, 3, Duration.ofMinutes(1));
        }

        assertThat(limiter.check(first, 3, Duration.ofMinutes(1)).allowed()).isFalse();
        assertThat(limiter.check(second, 3, Duration.ofMinutes(1)).allowed()).isTrue();
    }

    @Test
    void the_window_expires_so_a_caller_is_not_blocked_forever() throws InterruptedException {
        String bucket = bucket();
        limiter.check(bucket, 1, Duration.ofSeconds(1));
        assertThat(limiter.check(bucket, 1, Duration.ofSeconds(1)).allowed()).isFalse();

        // A real TTL in a real Redis, which is the reason this test uses a container: an
        // in-memory map would have let "the window expires" pass without a window existing.
        Thread.sleep(1_200);

        assertThat(limiter.check(bucket, 1, Duration.ofSeconds(1)).allowed()).isTrue();
    }

    @Test
    void the_window_starts_at_the_first_request_rather_than_sliding() throws InterruptedException {
        // Only the first request in a window sets the expiry. If every request reset it, a caller
        // sending steadily would never see the window end and would be blocked indefinitely.
        String bucket = bucket();
        limiter.check(bucket, 2, Duration.ofSeconds(2));
        Thread.sleep(1_100);
        limiter.check(bucket, 2, Duration.ofSeconds(2));
        Thread.sleep(1_100);

        assertThat(limiter.check(bucket, 2, Duration.ofSeconds(2)).allowed())
                .as("the window should have expired 2s after the FIRST request, not the last")
                .isTrue();
    }
}
