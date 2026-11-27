package in.drugwatch.api.risk.domain;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

/**
 * Calls the Phase 8 risk service.
 *
 * <p><b>The timeouts are the feature.</b> A model service that has stopped answering must not hold
 * a public web request open: a manufacturer page is mostly CDSCO data that is already in hand, and
 * a page taking thirty seconds to load is worse for a reader than one that loads at once saying
 * the score is unavailable. Two seconds to read is generous for an endpoint whose measured p95 is
 * 10 ms (docs/benchmarks.md §2).
 *
 * <p>Connect and read timeouts are set separately because they are different failures: "the host
 * is not there" should give up in a second, while "it accepted the connection and went quiet" is
 * the one that would otherwise hang the page.
 *
 * <p>Every failure becomes {@link Optional#empty()} rather than an exception thrown at the
 * controller. Rendering a page without a score is a normal outcome, not an error.
 */
@Component
public class RiskClient {

    private static final Logger log = LoggerFactory.getLogger(RiskClient.class);

    private final RestClient client;

    RiskClient(@Value("${drugwatch.risk.base-url}") String baseUrl, @Value("${drugwatch.risk.token:}") String token) {
        // HTTP/1.1, pinned. Java's HttpClient defaults to offering an HTTP/2 upgrade, which it
        // does by sending `Connection: Upgrade` and `Upgrade: h2c` with the body in chunked
        // transfer encoding. uvicorn - which serves the risk service - answers that request with
        // 422 "body: Field required": the headers arrive, the body does not.
        //
        // That was a genuinely nasty failure to find, because the fallback hid it perfectly: the
        // client turned the 422 into "no score today", which is exactly what it shows when the
        // service is down. In production this would have been a permanently missing score with no
        // error anywhere. The live test against the real service is what caught it.
        // 1s/2s until Phase 12, which was right while the risk service was a sibling container
        // one Docker network away (ADR 0017: measured p95 10 ms). It now lives on another host
        // across the internet, and measured from inside this container: DNS 0.21-0.38s, TCP
        // 0.27-0.45s, **TLS completing at up to 0.99s** - so a 1s connect timeout sat exactly on
        // the edge and failed intermittently with "HTTP connect timed out", reported to readers
        // as a permanently missing score. Warm request bodies come back in 0.28-0.50s.
        //
        // 3s each, so roughly 3x the worst measured, and a worst case around 6s rather than the
        // 30s ADR 0017 warned about. A **cold** service is a different thing entirely - Render
        // free spins down and takes ~113s to wake, which no sane timeout covers - so that is
        // handled by keeping it awake (step 9), not by waiting here.
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(3))
                .build());
        factory.setReadTimeout(Duration.ofSeconds(3));
        RestClient.Builder builder = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(factory)
                // Ask for an uncompressed body. Render's edge gzips JSON when the client
                // advertises gzip, and Java's HttpClient does **not** decompress it - so Spring
                // received gzipped bytes and failed with "Error while extracting response for
                // type [RiskExplanation] and content type [application/json]". Another silent
                // outage in the making, since this client reports every failure as "no score
                // today": a reader would simply never see one, with nothing in the log saying
                // why. The body is a few hundred bytes, so compressing it buys nothing here.
                .defaultHeader("Accept-Encoding", "identity");
        // Phase 12 (ADR 0021): the risk service runs on Render, reachable by anything that knows
        // its URL, so it checks a shared bearer token on every route. Empty locally, where
        // docker-compose sets no token and the service asks for none - so local dev is unchanged.
        if (!token.isBlank()) {
            builder = builder.defaultHeader("Authorization", "Bearer " + token);
        }
        this.client = builder.build();
    }

    /** A score and its explanation, or empty when the service cannot answer. */
    public Optional<RiskExplanation> explain(Map<String, Double> features) {
        try {
            RiskExplanation explanation = client.post()
                    .uri("/explain")
                    // Without an explicit content type the body is never serialised and the
                    // service answers 422 "Field required, body: null" - which this client would
                    // then report as "no score today", indistinguishable from the service being
                    // down. It looked like a working fallback and was a silent outage.
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("features", features, "top", 3))
                    .retrieve()
                    .body(RiskExplanation.class);
            return Optional.ofNullable(explanation);
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden rejected) {
            // Said separately and loudly. To a reader this looks the same as an outage, which is
            // how the HTTP/2 and content-type bugs above stayed hidden - but the cause is a
            // misconfigured RISK_API_TOKEN, which no amount of waiting fixes. A permanently
            // missing score with only "could not answer" in the log is the thing to avoid.
            log.error(
                    "the risk service refused this API's credentials ({}) - check RISK_API_TOKEN"
                            + " matches the value set on the risk service",
                    rejected.getStatusCode());
            return Optional.empty();
        } catch (RuntimeException failure) {
            // Timeouts, connection refused, and a 422 if the feature set ever drifts from the
            // model's. All of them mean the same thing to a reader: no score today.
            log.warn("the risk service could not answer: {}", failure.getMessage());
            return Optional.empty();
        }
    }

    /** What {@code /explain} returns (ADR 0017). */
    public record RiskExplanation(
            double score,
            Map<String, Object> model,
            List<Map<String, Object>> contributions,
            List<String> explanation,
            String limitations) {}
}
