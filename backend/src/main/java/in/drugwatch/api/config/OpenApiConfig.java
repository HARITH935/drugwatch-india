package in.drugwatch.api.config;

import in.drugwatch.api.shared.PublicNotes;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * The API's own description, published at {@code /v3/api-docs} and browsable at
 * {@code /swagger-ui.html}.
 *
 * <p>springdoc generates the endpoint list, the request and response shapes and the validation
 * rules from the code itself, so they cannot drift from what the API actually does. What it cannot
 * infer is why any of it exists, which is what this file supplies: the title, the caveats that
 * CLAUDE.md section 6 requires wherever this data is shown, and the fact that a bearer token is
 * how the watchlist is reached.
 *
 * <p>The disclaimer is in {@code info.description} rather than only on the website, because this
 * page is a page: somebody who finds the API before the site reads this and nothing else. It is
 * taken from {@link PublicNotes}, the same constants the JSON responses carry, so there is one
 * copy of the wording and not a second that quietly falls out of date.
 */
@Configuration
public class OpenApiConfig {

    private static final String BEARER_SCHEME = "bearer-token";

    private static final String DESCRIPTION = """
            Medicine quality intelligence built on CDSCO's monthly "Not of Standard Quality" and \
            spurious-drug alerts. The main endpoint is the batch checker: \
            `GET /api/v1/batches/search`.

            **%s**

            ### What this data does and does not say

            - %s
            - %s
            - %s
            - The manufacturer risk score describes **reporting history, not product quality**: \
            a company that was sampled more often has more findings to report. It is not a \
            prediction about any particular medicine.
            - Every finding carries its batch number, the alert month it came from, and a link to \
            the original CDSCO document, so any answer here can be checked against the source.

            ### Reaching the protected endpoints

            Everything under `/api/v1/watchlist` needs a bearer token: register, verify the \
            emailed link, then log in and send the `accessToken` as `Authorization: Bearer ...`. \
            Everything else is public, and the public lookups are rate-limited per caller.
            """.formatted(
                    PublicNotes.DISCLAIMER,
                    PublicNotes.FLAGGED_MEANING,
                    PublicNotes.NOT_FOUND_MEANING,
                    PublicNotes.SPURIOUS_MEANING);

    @Bean
    OpenAPI drugWatchOpenApi() {
        return new OpenAPI()
                .info(new Info()
                        .title("DrugWatch India API")
                        // The URL version, not the build version: a client cares which contract it
                        // is calling, and that only changes when /api/v1 becomes /api/v2.
                        .version("v1")
                        .description(DESCRIPTION)
                        // CDSCO's alerts are public documents; this records what the underlying
                        // data is rather than claiming a licence over it.
                        .license(new License().name("Source data: CDSCO public alerts (cdsco.gov.in)")))
                .components(new Components()
                        .addSecuritySchemes(
                                BEARER_SCHEME,
                                new SecurityScheme()
                                        .type(SecurityScheme.Type.HTTP)
                                        .scheme("bearer")
                                        .bearerFormat("JWT")
                                        .description("The `accessToken` from `POST /api/v1/auth/login`."
                                                + " Valid for 15 minutes.")));
        // Declared here but applied per endpoint with @SecurityRequirement, not globally: a global
        // requirement would label the public endpoints as needing a token, which is the opposite of
        // what this API is for.
    }
}
