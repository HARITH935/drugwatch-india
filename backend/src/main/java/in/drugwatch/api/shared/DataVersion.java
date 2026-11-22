package in.drugwatch.api.shared;

import java.time.Duration;
import java.time.Instant;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/**
 * Which version of the warehouse the API is serving: the newest alert month in it.
 *
 * <p>Used in every cache key, so the monthly pipeline run invalidates the cache simply by
 * producing a newer month. Nothing has to remember to flush anything.
 *
 * <p>The value itself is held for a minute. Without that, every cached lookup would run a
 * {@code max(alert_month)} query first - which would make the cache slower than the thing it is
 * caching for the cheapest endpoints. The hold is configurable ({@code
 * drugwatch.cache.version-hold}) and set to zero in tests: held for a minute, one test's freshly
 * inserted alert month leaks into the next test's cache keys.
 */
@Component
public class DataVersion {

    private static final String UNKNOWN = "none";

    private final JdbcClient jdbc;
    private final Duration heldFor;
    private volatile String current = null;
    private volatile Instant readAt = Instant.EPOCH;

    DataVersion(
            DataSource dataSource,
            @org.springframework.beans.factory.annotation.Value("${drugwatch.cache.version-hold:PT1M}")
                    Duration heldFor) {
        this.jdbc = JdbcClient.create(dataSource);
        this.heldFor = heldFor;
    }

    /** The newest alert month, e.g. {@code 2026-09}. */
    public String current() {
        Instant now = Instant.now();
        String held = current;
        if (held != null && readAt.plus(heldFor).isAfter(now)) {
            return held;
        }
        String fresh;
        try {
            fresh = jdbc.sql("SELECT coalesce(max(alert_month), 'none') FROM gold.fact_nsq_sample")
                    .query(String.class)
                    .single();
        } catch (RuntimeException unavailable) {
            // If the warehouse cannot be reached, keep serving the last known version rather than
            // changing every cache key at once - which would stampede the database at the moment
            // it is already unhappy.
            return held != null ? held : UNKNOWN;
        }
        current = fresh;
        readAt = now;
        return fresh;
    }
}
