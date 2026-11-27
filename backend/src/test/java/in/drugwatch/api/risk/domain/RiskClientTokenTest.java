package in.drugwatch.api.risk.domain;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Whether this client actually presents its bearer token (Phase 12 step 2).
 *
 * <p>Worth its own test because getting it wrong is invisible: the risk service answers 401, and
 * {@link RiskClient} turns every failure into "no score today" so a page would render without a
 * score and nothing would look broken. The same shape of silence already hid an HTTP/2 bug and a
 * content-type bug on this client, so the header is asserted rather than assumed.
 *
 * <p>Served by the JDK's own {@code HttpServer} - a real request over a real socket, with no new
 * test dependency to approve.
 */
class RiskClientTokenTest {

    private HttpServer server;
    private final AtomicReference<String> seenAuthorization = new AtomicReference<>();

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/explain", exchange -> {
            seenAuthorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            byte[] body = """
                    {"score":0.5,"model":{},"contributions":[],"explanation":[],"limitations":"x"}
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    private String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @Test
    void a_configured_token_is_sent_as_a_bearer_header() {
        new RiskClient(baseUrl(), "the-shared-secret").explain(Map.of("reports_6m", 1.0));

        assertThat(seenAuthorization.get()).isEqualTo("Bearer the-shared-secret");
    }

    @Test
    void no_token_means_no_header_at_all() {
        // Local dev: docker-compose sets no token and the service asks for none. An empty token
        // must not become the literal header "Bearer ", which the service would reject.
        new RiskClient(baseUrl(), "").explain(Map.of("reports_6m", 1.0));

        assertThat(seenAuthorization.get()).isNull();
    }
}
