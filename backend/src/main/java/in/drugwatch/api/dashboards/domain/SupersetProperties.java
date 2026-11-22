package in.drugwatch.api.dashboards.domain;

import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Where Superset is, who the API logs in as, and which dashboards may be embedded.
 *
 * <p>The allowlist is a map from a short public key to Superset's embedded UUID. Two reasons it is
 * a map rather than the UUID being passed in by the caller:
 *
 * <ul>
 *   <li><b>A caller cannot ask for a dashboard nobody listed.</b> If the request named a UUID, the
 *       endpoint would mint a token for any dashboard in Superset - including one built for
 *       internal use and never meant to be public.
 *   <li>The public URL carries {@code states} rather than
 *       {@code 09493340-7186-48b4-a333-d8697b2d2d7a}, so the frontend has nothing to leak and the
 *       UUID can be rotated without changing a published link.
 * </ul>
 */
@ConfigurationProperties(prefix = "drugwatch.superset")
public record SupersetProperties(String baseUrl, String username, String password, Map<String, String> dashboards) {

    public SupersetProperties {
        // A dashboard whose UUID is unset must not be in the allowlist. application.yaml declares
        // all four keys with empty defaults so the shape is visible, and without this filter an
        // unconfigured one would be published as embeddable and then mint a token for the UUID ""
        // - which Superset would refuse in a way that looks like an outage. A test caught it.
        dashboards = dashboards == null
                ? Map.of()
                : dashboards.entrySet().stream()
                        .filter(entry ->
                                entry.getValue() != null && !entry.getValue().isBlank())
                        .collect(java.util.stream.Collectors.toUnmodifiableMap(Map.Entry::getKey, Map.Entry::getValue));
    }
}
