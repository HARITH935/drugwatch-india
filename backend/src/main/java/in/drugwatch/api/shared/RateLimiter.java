package in.drugwatch.api.shared;

import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * A fixed-window request counter in Redis (plan §9 step 10, Phase 9 decision C).
 *
 * <p>About thirty lines rather than adding Bucket4j, because Redis is already in the stack and a
 * counter with an expiry is the whole algorithm: {@code INCR} the key, and if the count came back
 * as 1 give it a TTL. A fixed window lets a caller send up to twice the limit across a window
 * boundary, which a sliding window would not - and for "stop one script hammering the public
 * lookup" that is an acceptable edge, stated rather than hidden.
 *
 * <p><b>It fails open.</b> If Redis cannot be reached the request is allowed, and that is a
 * deliberate choice: this limiter sits in front of the batch checker, which is the reason the site
 * exists. Failing closed would mean a Redis blip takes down the public service - trading a real
 * outage for a hypothetical abuser. The warning is logged so the outage is visible.
 */
@Component
public class RateLimiter {

    private static final Logger log = LoggerFactory.getLogger(RateLimiter.class);

    private final StringRedisTemplate redis;

    RateLimiter(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /**
     * Count one request against {@code bucket}, and say whether it is within the limit.
     *
     * @return the number of requests left, or empty when the limit is already spent
     */
    public Decision check(String bucket, int limit, Duration window) {
        String key = "ratelimit:" + bucket;
        try {
            Long count = redis.opsForValue().increment(key);
            if (count == null) {
                return Decision.allowed(limit - 1, window);
            }
            if (count == 1L) {
                // Only the first request in a window sets the expiry, so the window starts at the
                // first request rather than sliding forward with every one.
                redis.expire(key, window);
            }
            if (count > limit) {
                Long remaining = redis.getExpire(key);
                return Decision.refused(
                        Duration.ofSeconds(remaining == null || remaining < 0 ? window.toSeconds() : remaining));
            }
            return Decision.allowed(limit - count.intValue(), window);
        } catch (RuntimeException unavailable) {
            log.warn("rate limiting is not working, so requests are being allowed: {}", unavailable.getMessage());
            return Decision.allowed(limit, window);
        }
    }

    /** Whether the request may proceed, and what to tell the caller. */
    public record Decision(boolean allowed, int remaining, Duration retryAfter) {

        static Decision allowed(int remaining, Duration window) {
            return new Decision(true, Math.max(remaining, 0), window);
        }

        static Decision refused(Duration retryAfter) {
            return new Decision(false, 0, retryAfter);
        }
    }
}
