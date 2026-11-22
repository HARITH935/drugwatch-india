package in.drugwatch.api;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.wait.strategy.Wait;

/**
 * A real Redis for the cache and rate-limit tests.
 *
 * <p>Not a mock and not an in-memory {@code ConcurrentMapCacheManager}: both would pass while the
 * things worth testing - that an {@code INCR} is atomic, that a TTL expires a window, that a cache
 * key actually changes when the warehouse does - are exactly the behaviours they do not have.
 *
 * <p>Testcontainers 2.0 publishes no Redis module, so this is the core project's {@code
 * GenericContainer} with {@code @ServiceConnection("redis")} telling Spring what it is. Static, so
 * one container serves the whole suite.
 */
@TestConfiguration(proxyBeanMethods = false)
class TestRedis {

    @Bean
    @ServiceConnection("redis")
    static GenericContainer<?> redis() {
        return new GenericContainer<>("redis:8.8").withExposedPorts(6379).waitingFor(Wait.forListeningPort());
    }
}
