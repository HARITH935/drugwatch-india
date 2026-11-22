package in.drugwatch.api.auth.api;

import in.drugwatch.api.auth.domain.AuthService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10's auth endpoints. */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService auth;

    AuthController(AuthService auth) {
        this.auth = auth;
    }

    /**
     * Always 202, whether or not the address was already registered.
     *
     * <p>The response is identical in both cases on purpose - see {@code AuthService}. 202 rather
     * than 201 because "created" would itself be the answer this endpoint refuses to give.
     */
    @PostMapping("/register")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, String> register(@Valid @RequestBody RegisterRequest request) {
        auth.register(request.email(), request.password());
        return Map.of(
                "status",
                "If that address can be registered, we have sent it an email. Confirm the address"
                        + " to finish creating the account.");
    }

    @PostMapping("/login")
    public AuthService.Tokens login(@Valid @RequestBody LoginRequest request) {
        return auth.login(request.email(), request.password());
    }

    @PostMapping("/refresh")
    public AuthService.Tokens refresh(@Valid @RequestBody RefreshRequest request) {
        return auth.refresh(request.refreshToken());
    }

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(@Valid @RequestBody RefreshRequest request) {
        auth.logout(request.refreshToken());
    }

    @PostMapping("/verify")
    public Map<String, String> verify(@Valid @RequestBody VerifyRequest request) {
        auth.verifyEmail(request.token());
        return Map.of("status", "Your email address is confirmed.");
    }

    /**
     * A 12-character minimum rather than a rule about symbols. Length is what makes a password
     * hard to guess; "must contain a digit and a capital" mostly produces Password1.
     */
    public record RegisterRequest(
            @NotBlank @Email @Size(max = 254) String email,
            @NotBlank @Size(min = 12, max = 200) String password) {}

    public record LoginRequest(
            @NotBlank @Size(max = 254) String email,
            @NotBlank @Size(max = 200) String password) {}

    public record RefreshRequest(@NotBlank @Size(max = 100) String refreshToken) {}

    public record VerifyRequest(@NotBlank @Size(max = 100) String token) {}
}
