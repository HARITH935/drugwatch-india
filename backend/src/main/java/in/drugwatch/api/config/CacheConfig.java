package in.drugwatch.api.config;

import in.drugwatch.api.alerts.domain.AlertService;
import in.drugwatch.api.batches.domain.BatchSearchResult;
import in.drugwatch.api.drugs.domain.DrugService;
import in.drugwatch.api.manufacturers.domain.ManufacturerService;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.JacksonJsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;

/**
 * Redis caching for the public lookups (plan §9 step 6).
 *
 * <p><b>Cache keys carry the data's alert month</b> (see {@link
 * in.drugwatch.api.shared.DataVersionKeyGenerator}), so a monthly warehouse load invalidates every
 * entry by itself. The alternative - a scheduled flush, or an endpoint Airflow calls after a run -
 * is another moving part that can fail silently, and its failure mode is the worst one available:
 * the site serving last month's answers while claiming to be current.
 *
 * <p><b>Each cache declares the one type it holds</b>, and that is not tidiness. A generic JSON
 * serializer writes an object without its type and hands back a {@code LinkedHashMap}, so every
 * cached endpoint fails on its second call with a {@code ClassCastException} - which is exactly
 * what happened here, and was invisible until a test read a value back rather than only checking
 * that a key existed. The alternative fix, turning on Jackson's default typing, writes the class
 * name into the cache and makes deserialisation polymorphic: a well-known attack surface, for a
 * cache where every entry has exactly one possible type anyway.
 */
@Configuration
@EnableCaching
public class CacheConfig {

    /** Cache names, so a typo in an annotation does not create a second silent cache. */
    public static final String DRUG_PAGES = "drugPages";

    public static final String DRUG_SEARCHES = "drugSearches";
    public static final String MANUFACTURER_PAGES = "manufacturerPages";
    public static final String LATEST_ALERTS = "latestAlerts";
    public static final String BATCH_SEARCHES = "batchSearches";

    /** How long each cache keeps an entry, and what it is allowed to hold. */
    private static final Map<String, Duration> LIFETIMES = Map.of(
            // The archive is rebuilt monthly, so six hours is a compromise: long enough to absorb
            // a traffic spike on one medicine, short enough that a correction reaches readers the
            // same day even if the alert month has not changed.
            DRUG_PAGES, Duration.ofHours(6),
            MANUFACTURER_PAGES, Duration.ofHours(6),
            // Searches are cheap to recompute and far more varied, so a shorter life stops one
            // crawler filling Redis with single-use keys.
            DRUG_SEARCHES, Duration.ofMinutes(30),
            BATCH_SEARCHES, Duration.ofMinutes(30),
            // One key for everybody, and the cheapest thing here to be wrong about.
            LATEST_ALERTS, Duration.ofHours(1));

    @Bean
    RedisCacheManager cacheManager(RedisConnectionFactory connections) {
        Map<String, RedisCacheConfiguration> caches = new LinkedHashMap<>();
        caches.put(DRUG_PAGES, cacheFor(DrugService.DrugPage.class, LIFETIMES.get(DRUG_PAGES)));
        caches.put(DRUG_SEARCHES, cacheFor(DrugService.DrugSearchResult.class, LIFETIMES.get(DRUG_SEARCHES)));
        caches.put(
                MANUFACTURER_PAGES,
                cacheFor(ManufacturerService.ManufacturerPage.class, LIFETIMES.get(MANUFACTURER_PAGES)));
        caches.put(LATEST_ALERTS, cacheFor(AlertService.LatestAlerts.class, LIFETIMES.get(LATEST_ALERTS)));
        caches.put(BATCH_SEARCHES, cacheFor(BatchSearchResult.class, LIFETIMES.get(BATCH_SEARCHES)));

        return RedisCacheManager.builder(connections)
                // No default configuration: a cache name that is not declared above is a mistake,
                // and it should fail rather than quietly get a generic serializer that breaks on
                // the second read.
                .withInitialCacheConfigurations(caches)
                .disableCreateOnMissingCache()
                .build();
    }

    private static RedisCacheConfiguration cacheFor(Class<?> type, Duration ttl) {
        return RedisCacheConfiguration.defaultCacheConfig()
                .serializeValuesWith(RedisSerializationContext.SerializationPair.fromSerializer(
                        new JacksonJsonRedisSerializer<>(type)))
                // Never cache a null. A miss cached as a hit means a medicine added next month
                // keeps reporting "no such medicine" until the TTL expires.
                .disableCachingNullValues()
                .entryTtl(ttl);
    }
}
