package in.drugwatch.api.auth.domain;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;

/**
 * Random tokens, and the hashes that are stored instead of them.
 *
 * <p>Refresh tokens and email-verification links are bearer credentials: whoever holds one is the
 * user. So the database holds only a hash, exactly as it does for passwords. If {@code
 * app.refresh_tokens} leaks, what leaks is a list of hashes that cannot be presented to the API.
 *
 * <p>SHA-256 rather than BCrypt here, deliberately, and the difference is worth stating: BCrypt is
 * slow <i>on purpose</i> to make guessing a human-chosen password expensive. These tokens are 256
 * bits of {@link SecureRandom}, so guessing is already impossible and the slowness would only cost
 * a hash on every single API call that refreshes.
 */
final class TokenHash {

    private static final SecureRandom RANDOM = new SecureRandom();

    private TokenHash() {}

    /** A new token: 256 bits, URL-safe, shown to the user exactly once. */
    static String newToken() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    /** What gets stored. */
    static String hash(String token) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is required by the Java platform", impossible);
        }
    }
}
