package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

import in.drugwatch.api.drugs.domain.DrugService;
import in.drugwatch.api.shared.DataVersion;
import java.time.Duration;
import java.util.Set;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.jdbc.Sql;

/**
 * Caching, and the property that makes it safe to cache CDSCO data at all.
 *
 * <p>A stale answer here is not a performance problem, it is a wrong answer about somebody's
 * medicine. So the test that matters is that a new alert month changes every key.
 */
@SpringBootTest
@Import({TestDatabase.class, TestRedis.class})
@Sql("classpath:db/gold-fixture.sql")
class CachingTest {

    @Autowired
    DrugService drugs;

    @Autowired
    StringRedisTemplate redis;

    @Autowired
    DataVersion dataVersion;

    @Autowired
    DataSource dataSource;

    private Set<String> cacheKeys() {
        return redis.keys("drugPages*");
    }

    /**
     * Removes only this cache's keys, not everything in Redis.
     *
     * <p>This used to be {@code getConnectionFactory().getConnection().serverCommands().flushAll()},
     * which opened a connection nothing closed and wiped every other test's keys too, the rate
     * limiter's counters included. It was not the cause of this class's flakiness (see {@link
     * #awaitCached}); that turned out to be timing.
     */
    private void clearDrugPages() {
        redis.delete(cacheKeys());
    }

    /**
     * Waits (briefly) for a cache entry instead of asserting the instant the method returns.
     *
     * <p>The cache write is not finished when the cached method returns: it reaches Redis a few
     * milliseconds later. Measured directly - a key that the test's own template could not yet see
     * was visible to a second connection asked a moment later, and to the template within ~20 ms.
     * That is harmless for the site (the next request finds the entry), but asserting immediately
     * made this class fail on roughly every other run, a different test each time. Two seconds is
     * a ceiling, not a delay: the wait returns as soon as the entry is there.
     */
    private Set<String> awaitCached(String monthPrefix) {
        await().atMost(Duration.ofSeconds(2))
                .untilAsserted(() -> assertThat(cacheKeys())
                        .anySatisfy(key -> assertThat(key).contains(monthPrefix)));
        return cacheKeys();
    }

    @Test
    void a_drug_page_is_cached() {
        clearDrugPages();

        drugs.page("d1");

        assertThat(awaitCached("page:[d1]")).isNotEmpty();
    }

    @Test
    void the_cache_key_carries_the_alert_month() {
        // This is what makes the monthly pipeline invalidate the cache by itself: the key changes
        // because the data changed, so nothing has to remember to flush anything - and the
        // failure mode that matters, serving last month's answers as current, cannot happen.
        clearDrugPages();

        drugs.page("d1");

        awaitCached("2026-03:page:[d1]");
    }

    @Test
    void a_new_alert_month_makes_the_old_entries_unreachable() {
        clearDrugPages();
        drugs.page("d1");
        Set<String> before = awaitCached("2026-03:page:[d1]");

        // The monthly load: a newer alert month appears in the warehouse.
        JdbcClient.create(dataSource).sql("""
                        INSERT INTO gold.fact_nsq_sample
                            (sample_id, drug_id, manufacturer_id, batch_no, alert_month, alert_month_start,
                             failure_reason, failure_categories, is_spurious, reported_by, lab_type, source_url)
                        VALUES ('s-new', 'd1', 'm1', 'NEW-1', '2026-04', DATE '2026-04-01', 'Assay',
                                ARRAY['Assay'], false, 'DTL Shimla', 'State', 'https://example.invalid/a.pdf')
                        """).update();
        // The hold is zero in tests (see application.properties), so the next call already sees
        // the new month - no waiting, and no dependence on timing.
        assertThat(dataVersion.current()).isEqualTo("2026-04");

        drugs.page("d1");

        // Asserted as "the new month's key exists and the old one is no longer asked for",
        // rather than by counting keys: other test classes share this Redis and flush it, so a
        // count is not a stable thing to assert. The property is what matters anyway.
        assertThat(before).anySatisfy(key -> assertThat(key).contains("2026-03"));
        awaitCached("2026-04:page:[d1]");
    }

    @Test
    void the_second_call_does_not_reach_the_database() {
        clearDrugPages();
        var first = drugs.page("d1");
        // Wait for the entry to land before deleting the row: otherwise the second call can miss a
        // write still in flight, go to the database, and fail for a reason unrelated to caching.
        awaitCached("2026-03:page:[d1]");

        // Delete the row the page is built from. A cached answer survives; an uncached one would
        // now throw NotFoundException - which is how this proves the cache was used rather than
        // just populated.
        JdbcClient.create(dataSource)
                .sql("DELETE FROM gold.dim_drug WHERE drug_id = 'd1'")
                .update();

        var second = drugs.page("d1");

        assertThat(second.drug().productName()).isEqualTo(first.drug().productName());
    }

    @Test
    void the_data_version_is_the_newest_alert_month() {
        assertThat(dataVersion.current()).isEqualTo("2026-03");
    }
}
