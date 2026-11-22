package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.drugs.domain.DrugService;
import in.drugwatch.api.shared.DataVersion;
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

    @Test
    void a_drug_page_is_cached() {
        redis.getConnectionFactory().getConnection().serverCommands().flushAll();

        drugs.page("d1");

        assertThat(cacheKeys()).isNotEmpty();
    }

    @Test
    void the_cache_key_carries_the_alert_month() {
        // This is what makes the monthly pipeline invalidate the cache by itself: the key changes
        // because the data changed, so nothing has to remember to flush anything - and the
        // failure mode that matters, serving last month's answers as current, cannot happen.
        redis.getConnectionFactory().getConnection().serverCommands().flushAll();

        drugs.page("d1");

        assertThat(cacheKeys()).anySatisfy(key -> assertThat(key).contains("2026-03"));
    }

    @Test
    void a_new_alert_month_makes_the_old_entries_unreachable() {
        redis.getConnectionFactory().getConnection().serverCommands().flushAll();
        drugs.page("d1");
        Set<String> before = cacheKeys();

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

        assertThat(cacheKeys()).hasSizeGreaterThan(before.size());
        assertThat(cacheKeys()).anySatisfy(key -> assertThat(key).contains("2026-04"));
    }

    @Test
    void the_second_call_does_not_reach_the_database() {
        redis.getConnectionFactory().getConnection().serverCommands().flushAll();
        var first = drugs.page("d1");

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
