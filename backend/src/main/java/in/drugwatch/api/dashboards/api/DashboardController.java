package in.drugwatch.api.dashboards.api;

import in.drugwatch.api.dashboards.domain.GuestTokenService;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10: {@code POST /api/v1/dashboards/{key}/guest-token}, public and rate-limited. */
@RestController
@RequestMapping("/api/v1/dashboards")
@Validated
public class DashboardController {

    private final GuestTokenService tokens;

    DashboardController(GuestTokenService tokens) {
        this.tokens = tokens;
    }

    /**
     * A short-lived token for one allowlisted dashboard.
     *
     * <p>POST rather than GET because it mints a credential: a GET would be cached by a browser,
     * a proxy or a CDN, and a cached bearer token is a token handed to whoever asks next.
     *
     * <p>The key is restricted to lower-case letters, digits and hyphens. It is only ever used as
     * a map lookup, so nothing can be injected through it - but a value that cannot be a key at
     * all should be rejected before it reaches the lookup rather than after.
     */
    @PostMapping("/{key}/guest-token")
    public GuestTokenService.GuestToken guestToken(
            @PathVariable @NotBlank @Size(max = 64) @Pattern(regexp = "[a-z0-9-]+") String key) {
        return tokens.tokenFor(key);
    }

    /** Which dashboards a client may embed. Saves the frontend hardcoding the list. */
    @GetMapping
    public Map<String, Object> available() {
        return Map.of("dashboards", tokens.embeddableKeys());
    }
}
