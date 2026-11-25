package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.dashboards.domain.GuestTokenService;
import java.util.Base64;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * A real guest token from the real Superset.
 *
 * <p>Phase 9's done-when says "the guest-token endpoint returns a valid Superset token", and the
 * only way to know that is to ask Superset. The settings come from the environment, so this uses
 * the same service account and UUIDs the running stack does.
 */
@SpringBootTest
@Import({TestDatabase.class, TestRedis.class})
@EnabledIfEnvironmentVariable(
        named = "SUPERSET_EMBED_PASSWORD",
        matches = ".+",
        disabledReason = "needs the superset container and configure_embedding.py having been run")
class GuestTokenLiveTest {

    /**
     * Points the service at the real Superset, overriding the dead port the other tests use.
     * Read from the environment rather than hardcoded so this cannot drift from the stack.
     */
    @DynamicPropertySource
    static void realSuperset(DynamicPropertyRegistry registry) {
        registry.add(
                "drugwatch.superset.base-url",
                () -> System.getenv().getOrDefault("SUPERSET_URL", "http://localhost:8088"));
        registry.add("drugwatch.superset.username", () -> System.getenv("SUPERSET_EMBED_USERNAME"));
        registry.add("drugwatch.superset.password", () -> System.getenv("SUPERSET_EMBED_PASSWORD"));
        registry.add("drugwatch.superset.dashboards.states", () -> System.getenv("SUPERSET_DASHBOARD_STATES"));
    }

    @Autowired
    GuestTokenService tokens;

    @Test
    void superset_issues_a_token_for_an_allowlisted_dashboard() {
        var token = tokens.tokenFor("states");

        assertThat(token.dashboard()).isEqualTo("states");
        assertThat(token.token()).isNotBlank();
        assertThat(token.expiresInSeconds()).isEqualTo(300);
    }

    @Test
    void the_token_is_a_jwt_scoped_to_that_one_dashboard() {
        // Decoded rather than taken on trust: a token that happened to carry every dashboard, or
        // a role with write permissions, would still look like a working token from outside.
        var token = tokens.tokenFor("states");
        String payload = decodeJwtPayload(token.token());

        assertThat(payload).contains("\"type\":\"guest\"");
        assertThat(payload).contains(System.getenv("SUPERSET_DASHBOARD_STATES"));
        // Exactly one resource: the dashboard asked for.
        assertThat(payload.split("\"type\":\"dashboard\"", -1).length - 1).isEqualTo(1);
    }

    @Test
    void the_token_does_not_carry_the_service_accounts_identity() {
        // The guest is anonymous. If the token named the service account, Superset would resolve
        // it to that user's roles rather than the read-only EmbeddedViewer role.
        var token = tokens.tokenFor("states");
        String payload = decodeJwtPayload(token.token());

        assertThat(payload).contains("guest");
        assertThat(payload).doesNotContain(System.getenv("SUPERSET_EMBED_USERNAME"));
    }

    /**
     * The JWT's middle segment, base64url-decoded.
     *
     * <p>{@code Base64.getUrlDecoder()} needs the segment padded to a multiple of 4 - but padding
     * to the number of {@code =} characters the segment is actually missing, not blindly
     * appending {@code "=="} and then trimming back to a multiple of 4 of the ORIGINAL (unpadded)
     * length. That trim point is 2 or 3 characters short of the real padded length whenever the
     * segment's length is 2 or 3 mod 4 - the common case - silently dropping real trailing bytes
     * of the payload (the token's last field, {@code "type":"guest"}, missing its closing brace)
     * rather than failing loudly. Found because it flaked: the token's `iat`/`exp` are
     * variable-width floating-point timestamps, so the segment's length mod 4 differs run to run,
     * and only the 25% of runs where it was already 0 mod 4 happened to decode correctly.
     */
    private static String decodeJwtPayload(String jwt) {
        String segment = jwt.split("\\.")[1];
        String padded = segment + "=".repeat((4 - segment.length() % 4) % 4);
        return new String(Base64.getUrlDecoder().decode(padded));
    }
}
