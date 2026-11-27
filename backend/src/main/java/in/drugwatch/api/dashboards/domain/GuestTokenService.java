package in.drugwatch.api.dashboards.domain;

import in.drugwatch.api.shared.NotFoundException;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

/**
 * Mints a short-lived Superset guest token for an allowlisted dashboard (plan §9 step 8).
 *
 * <p>The point of doing this server-side is that <b>the Superset credentials never reach a
 * browser</b>. The frontend asks this endpoint for a token, which is good for five minutes, scoped
 * to one dashboard, and carries a role that can only read. Phase 6's
 * {@code configure_public_role.py} deliberately refused {@code can_grant_guest_token} to anonymous
 * visitors and noted that Phase 9 would do it here; this is that.
 *
 * <p>The account it logs in as holds exactly one permission - {@code can_grant_guest_token} - so a
 * leak of this password buys the ability to mint tokens for dashboards that are already public,
 * and nothing else. It cannot read a dataset, run a query or edit a chart.
 *
 * <p>HTTP/1.1 is pinned for the same reason as the risk client: Java's default HTTP/2 upgrade
 * attempt loses the request body against some servers, and the failure looks like an outage.
 */
@Service
public class GuestTokenService {

    private static final Logger log = LoggerFactory.getLogger(GuestTokenService.class);

    /** Matches {@code GUEST_TOKEN_JWT_EXP_SECONDS} in superset_config.py. */
    private static final int TOKEN_LIFETIME_SECONDS = 300;

    private final SupersetProperties superset;
    private final RestClient client;

    GuestTokenService(SupersetProperties superset) {
        this.superset = superset;
        // Phase 12 moved Superset onto another host across the internet, so these are no longer
        // local-network timings. Measured from inside the API container against the deployed
        // Superset, warm: TLS completes in 0.75-1.25s and a login takes 2.0-2.7s in total - so
        // the previous 2s connect sat close to the edge. 4s/6s is roughly 3x and 2x the worst
        // measured.
        //
        // A **cold** Superset is not covered on purpose: Render free spins it down and a login
        // then takes ~55s (measured), which is far too long to hold a page open for. Keeping it
        // awake is step 9's job; until then a first visit after an idle spell shows the page
        // without its dashboards rather than hanging.
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(4))
                .build());
        factory.setReadTimeout(Duration.ofSeconds(6));
        this.client = RestClient.builder()
                .baseUrl(superset.baseUrl())
                .requestFactory(factory)
                // Superset refused the guest-token POST in production with
                //   400 Bad Request: The referrer header is missing.
                // That is Flask-WTF's CSRF check, which on an HTTPS request requires a Referer
                // whose host matches the request's. A browser sends one; a server-to-server call
                // does not, and it never came up locally because Talisman - and so HTTPS - is
                // off there. Superset's own base URL is the honest value: this request really
                // does originate from a client acting on that site's behalf.
                .defaultHeader("Referer", superset.baseUrl())
                // Same reasoning as RiskClient: Java's HttpClient does not decompress, and
                // Render's edge gzips JSON for any client that advertises support.
                .defaultHeader("Accept-Encoding", "identity")
                .build();
    }

    /** A guest token for one allowlisted dashboard. */
    public GuestToken tokenFor(String dashboardKey) {
        String uuid = superset.dashboards().get(dashboardKey);
        if (uuid == null) {
            // 404, not 403: whether a key exists is not worth telling a caller, and every
            // allowlisted key is published by the endpoint below anyway.
            throw new NotFoundException("No such dashboard");
        }
        // The UUID is returned here too, not just kept server-side: the embedded SDK's
        // embedDashboard() runs in the browser and needs it to build the iframe's src, so there
        // is no way to embed at all without the viewer's own page learning it. That is a
        // different question from the one embeddableKeys()'s own "keys only" rule answers - a
        // caller still cannot mint a token for a UUID it supplies itself, only for one this
        // lookup already resolved from an allowlisted key.
        return new GuestToken(dashboardKey, uuid, requestGuestToken(login(), uuid), TOKEN_LIFETIME_SECONDS);
    }

    /**
     * The keys a client may ask for.
     *
     * <p>Only the keys - never the UUIDs. A published UUID would let anybody holding a stolen
     * service password mint tokens without having to discover the dashboards first.
     */
    public Set<String> embeddableKeys() {
        return new TreeSet<>(superset.dashboards().keySet());
    }

    /**
     * What Superset needs on a write: a bearer token, a CSRF token, and the session cookie issued
     * alongside that CSRF token.
     *
     * <p>All three, together. Phase 6's {@code superset_api.py} had to do the same dance and left a
     * note that this endpoint would too. Without the CSRF token Superset answers 400 "The CSRF
     * token is missing"; without the matching cookie it rejects the CSRF token as unknown.
     */
    private record Session(String accessToken, String csrfToken, String cookie) {}

    /**
     * Logs in and completes the CSRF handshake.
     *
     * <p>Done on every request rather than holding a session: the token is short-lived, the call
     * happens once per embedded dashboard view, and a cached session is a thing that can go stale
     * in a way that is awkward to detect. If this ever becomes hot, the fix is to cache the access
     * token with a safety margin - not to keep a long-lived session.
     */
    private Session login() {
        try {
            Map<?, ?> loggedIn = client.post()
                    .uri("/api/v1/security/login")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "username",
                            superset.username(),
                            "password",
                            superset.password(),
                            "provider",
                            "db",
                            "refresh",
                            false))
                    .retrieve()
                    .body(Map.class);
            Object accessToken = loggedIn == null ? null : loggedIn.get("access_token");
            if (accessToken == null) {
                throw new DashboardUnavailableException("Superset accepted the login but returned no token");
            }

            // The CSRF token and its cookie come from one response and are only valid together,
            // so both are read from the same exchange rather than fetched separately.
            var csrf = client.get()
                    .uri("/api/v1/security/csrf_token/")
                    .header("Authorization", "Bearer " + accessToken)
                    .retrieve()
                    .toEntity(Map.class);
            Object csrfToken = csrf.getBody() == null ? null : csrf.getBody().get("result");
            List<String> cookies = csrf.getHeaders().get("Set-Cookie");
            if (csrfToken == null || cookies == null || cookies.isEmpty()) {
                throw new DashboardUnavailableException("Superset did not issue a CSRF token");
            }
            // Only the name=value part: the attributes (Path, HttpOnly, SameSite) are instructions
            // to a browser, and Superset does not expect them echoed back.
            String cookie = cookies.getFirst().split(";", 2)[0];

            return new Session(accessToken.toString(), csrfToken.toString(), cookie);
        } catch (DashboardUnavailableException already) {
            throw already;
        } catch (RuntimeException failure) {
            // The password is never in the message, and the message never reaches the caller.
            log.error("could not log in to Superset to mint a guest token: {}", failure.getMessage());
            throw new DashboardUnavailableException("The dashboard service is temporarily unavailable");
        }
    }

    private String requestGuestToken(Session session, String dashboardUuid) {
        try {
            Map<?, ?> response = client.post()
                    .uri("/api/v1/security/guest_token/")
                    .header("Authorization", "Bearer " + session.accessToken())
                    .header("X-CSRFToken", session.csrfToken())
                    .header("Cookie", session.cookie())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            // Anonymous. These dashboards are public CDSCO data and every viewer
                            // sees the same thing, so there is no identity to pass - and naming
                            // the service account here would have Superset resolve the token to
                            // that user's roles rather than the read-only EmbeddedViewer role.
                            "user",
                            Map.of("username", "guest", "first_name", "Guest", "last_name", "Viewer"),
                            // One resource: the dashboard that was asked for, and no other.
                            "resources",
                            List.of(Map.of("type", "dashboard", "id", dashboardUuid)),
                            // No row-level security rules: there is no per-viewer slice of a
                            // public archive, so a rule here would imply one that does not exist.
                            "rls",
                            List.of()))
                    .retrieve()
                    .body(Map.class);
            Object token = response == null ? null : response.get("token");
            if (token == null) {
                throw new DashboardUnavailableException("Superset returned no guest token");
            }
            return token.toString();
        } catch (DashboardUnavailableException already) {
            throw already;
        } catch (RuntimeException failure) {
            log.error("Superset refused to mint a guest token: {}", failure.getMessage());
            throw new DashboardUnavailableException("The dashboard service is temporarily unavailable");
        }
    }

    /** A token, the dashboard it is for (its public key and Superset's own id), and how long it lasts. */
    public record GuestToken(String dashboard, String dashboardId, String token, int expiresInSeconds) {}

    /** Superset could not be reached or refused. The caller gets 503, never the detail. */
    public static class DashboardUnavailableException extends RuntimeException {
        public DashboardUnavailableException(String message) {
            super(message);
        }
    }
}
