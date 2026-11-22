package in.drugwatch.api.auth.domain;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import java.time.Duration;
import java.time.Instant;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.stereotype.Component;

/**
 * Issues the short-lived access token.
 *
 * <p><b>Fifteen minutes</b>, which is the whole reason there are two kinds of token. An access
 * token is presented on every request and cannot be withdrawn once issued - nothing checks a
 * database for it, which is what makes it fast - so the only limit on a stolen one is how soon it
 * expires. The refresh token is the long-lived half, it is stored, and it <i>can</i> be revoked.
 *
 * <p>Signed with HMAC rather than a key pair: one service issues these and the same service
 * verifies them, so a shared secret is enough and there is no public key anybody needs. If a
 * second service ever has to verify a token without being able to mint one, this becomes RSA.
 */
@Component
public class AccessTokens {

    static final Duration LIFETIME = Duration.ofMinutes(15);

    private final JwtEncoder encoder;

    AccessTokens(@Value("${drugwatch.auth.jwt-secret}") String secret) {
        // Rejected rather than padded: a short secret makes a forgeable signature, and padding it
        // silently would hide that. 32 bytes is the minimum for HS256.
        if (secret == null || secret.getBytes().length < 32) {
            throw new IllegalStateException(
                    "drugwatch.auth.jwt-secret must be at least 32 bytes; generate one with: openssl rand -hex 32");
        }
        this.encoder = new NimbusJwtEncoder(new ImmutableSecret<>(new SecretKeySpec(secret.getBytes(), "HmacSHA256")));
    }

    /** A signed token naming the user and their role. */
    public String issue(Long userId, String email, String role, Instant now) {
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer("drugwatch-api")
                .subject(String.valueOf(userId))
                .issuedAt(now)
                .expiresAt(now.plus(LIFETIME))
                .claim("email", email)
                // Spring Security's default converter reads authorities from "scope"; naming it
                // here rather than configuring a custom converter keeps the filter chain plain.
                .claim("scope", "ROLE_" + role)
                .build();
        return encoder.encode(JwtEncoderParameters.from(
                        JwsHeader.with(MacAlgorithm.HS256).build(), claims))
                .getTokenValue();
    }

    public long lifetimeSeconds() {
        return LIFETIME.toSeconds();
    }
}
