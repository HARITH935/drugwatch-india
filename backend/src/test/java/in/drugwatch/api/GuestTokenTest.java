package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import in.drugwatch.api.dashboards.domain.GuestTokenService;
import in.drugwatch.api.shared.NotFoundException;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

/**
 * The guest-token endpoint with Superset unreachable.
 *
 * <p>That is the default in tests, because the allowlist is the part worth testing and it decides
 * before any network call happens: a key nobody listed is refused whether Superset is up or not.
 */
@SpringBootTest
@Import({TestDatabase.class, TestRedis.class})
class GuestTokenTest {

    @Autowired
    GuestTokenService tokens;

    @Test
    void a_dashboard_nobody_listed_is_refused_before_superset_is_called() {
        // The reason the allowlist is a map rather than a UUID in the request: otherwise this
        // endpoint would mint a token for any dashboard in Superset, including one built for
        // internal use and never meant to be public.
        assertThatThrownBy(() -> tokens.tokenFor("not-a-listed-dashboard"))
                .isInstanceOf(NotFoundException.class)
                .hasMessage("No such dashboard");
    }

    @Test
    void a_listed_dashboard_gets_as_far_as_calling_superset() {
        // Superset is unreachable in tests, so this proves the allowlist passed and the call was
        // attempted - and that the failure is reported as unavailability rather than "no such
        // dashboard", which would send the frontend looking for a bug in its own key.
        assertThatThrownBy(() -> tokens.tokenFor("states"))
                .isInstanceOf(GuestTokenService.DashboardUnavailableException.class)
                .hasMessageContaining("temporarily unavailable");
    }

    @Test
    void the_failure_message_never_names_superset_or_the_account() {
        // A caller does not need to learn that the dashboard service exists, where it is, or what
        // it said. The detail is in the log.
        try {
            tokens.tokenFor("states");
        } catch (GuestTokenService.DashboardUnavailableException expected) {
            assertThat(expected.getMessage())
                    .doesNotContainIgnoringCase("superset")
                    .doesNotContainIgnoringCase("test-embed")
                    .doesNotContainIgnoringCase("test-only")
                    .doesNotContain("59998");
        }
    }

    @Test
    void the_published_list_carries_keys_and_never_uuids() {
        // A published UUID would let anybody holding a stolen service password mint tokens
        // without having to discover the dashboards first.
        // Asserted as a property rather than an exact list: when the suite runs with .env loaded,
        // application.yaml picks up the real dashboard UUIDs too, so the number of listed keys
        // depends on the machine. What must hold everywhere is that every entry is a key.
        assertThat(tokens.embeddableKeys()).contains("drug-classes", "states");
        assertThat(tokens.embeddableKeys())
                .allSatisfy(key -> assertThat(key).matches("[a-z0-9-]+").doesNotMatch("[0-9a-f]{8}-[0-9a-f]{4}-.*"));
    }
}
