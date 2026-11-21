package in.drugwatch.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * The application starts, and reports its health over a real port.
 *
 * <p>One full-context test, deliberately: it is the only level that catches a context that fails
 * to start, which is the failure that makes every other test irrelevant. The rest of the suite
 * uses slices, because a full Spring context per test class is the usual reason a Java test suite
 * becomes too slow to run.
 *
 * <p>The client is {@link RestTestClient}, not {@code TestRestTemplate}: Spring Boot 4 removed the
 * latter.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class ApplicationSmokeTest {

    @Autowired
    RestTestClient client;

    @Test
    void the_application_starts_and_reports_health() {
        client.get()
                .uri("/actuator/health")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.status")
                .isEqualTo("UP");
    }

    @Test
    void health_does_not_leak_which_internal_services_exist() {
        // Actuator will happily publish every component it knows about - the database, Redis, the
        // risk service - with their state. That is a map of the internals for anyone who asks, and
        // this is the service Phase 12 exposes. application.yaml turns it off; this checks it.
        client.get()
                .uri("/actuator/health")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.components")
                .doesNotExist();
    }

    @Test
    void only_health_is_exposed_over_http() {
        // /actuator/env prints configuration, which in production includes the shape of every
        // secret the service was given. It must not be reachable.
        client.get().uri("/actuator/env").exchange().expectStatus().isNotFound();
        client.get().uri("/actuator/beans").exchange().expectStatus().isNotFound();
    }
}
