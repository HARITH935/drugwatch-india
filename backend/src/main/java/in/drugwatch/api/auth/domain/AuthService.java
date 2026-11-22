package in.drugwatch.api.auth.domain;

import in.drugwatch.api.shared.NotFoundException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Locale;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Registration, login, refresh and email verification.
 *
 * <p>Three rules shape almost everything here, and each one costs something:
 *
 * <ol>
 *   <li><b>Registering never reveals whether an address already has an account.</b> A site about
 *       the medicines people take is a place where "does this person have an account here" is
 *       itself private, and a public endpoint that answers it is an oracle anyone can query. So
 *       registration gives the same response either way, and when the address is already taken it
 *       sends that address a note instead of creating anything.
 *   <li><b>Nothing is emailed to an address that has not confirmed itself</b> (decision E).
 *       Otherwise anyone can register with a stranger's address, add watch terms, and have the
 *       site email that stranger about medicine alerts under CDSCO's name.
 *   <li><b>Refresh tokens are single-use and rotate.</b> Presenting one returns a new one and
 *       revokes the old. Presenting an already-revoked token means it was copied, so every token
 *       that user holds is revoked at once.
 * </ol>
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    private static final Duration REFRESH_LIFETIME = Duration.ofDays(30);
    private static final Duration VERIFICATION_LIFETIME = Duration.ofHours(24);

    private final UserRepository users;
    private final RefreshTokenRepository refreshTokens;
    private final EmailVerificationRepository verifications;
    private final PasswordEncoder passwords;
    private final AccessTokens accessTokens;
    private final AuthMailer mailer;
    private final Clock clock;

    AuthService(
            UserRepository users,
            RefreshTokenRepository refreshTokens,
            EmailVerificationRepository verifications,
            PasswordEncoder passwords,
            AccessTokens accessTokens,
            AuthMailer mailer,
            Clock clock) {
        this.users = users;
        this.refreshTokens = refreshTokens;
        this.verifications = verifications;
        this.passwords = passwords;
        this.accessTokens = accessTokens;
        this.mailer = mailer;
        this.clock = clock;
    }

    /**
     * Create an account, or do nothing and say the same thing.
     *
     * <p>The caller cannot tell which happened. That is the point.
     */
    @Transactional
    public void register(String rawEmail, String password) {
        String email = normalise(rawEmail);

        if (users.existsByEmail(email)) {
            // Not an error, and not silence either: the person who owns the address is told that
            // somebody tried, which is useful to them and useless to whoever tried.
            mailer.sendAlreadyRegistered(email);
            log.info("registration attempted for an address that already has an account");
            return;
        }

        UserEntity user = users.save(new UserEntity(email, passwords.encode(password)));
        sendVerification(user);
    }

    /** Issue a fresh verification link. Used by registration and by "resend". */
    private void sendVerification(UserEntity user) {
        String token = TokenHash.newToken();
        verifications.save(new EmailVerificationEntity(
                user.getId(), TokenHash.hash(token), clock.instant().plus(VERIFICATION_LIFETIME)));
        mailer.sendVerification(user.getEmail(), token);
    }

    /**
     * Confirm an address.
     *
     * <p>Single-use and time-limited: a link that stays valid forever is a credential sitting in
     * somebody's inbox, and inboxes get forwarded, backed up and breached.
     */
    @Transactional
    public void verifyEmail(String token) {
        Instant now = clock.instant();
        EmailVerificationEntity verification = verifications
                .findByTokenHash(TokenHash.hash(token))
                .filter(candidate -> candidate.isUsable(now))
                .orElseThrow(() -> new InvalidCredentialsException("That verification link is not valid"));

        UserEntity user =
                users.findById(verification.getUserId()).orElseThrow(() -> new NotFoundException("No such account"));
        user.markEmailVerified();
        verification.markUsed(now);
    }

    /**
     * Log in.
     *
     * <p>The password is checked even when the address is unknown. Skipping the hash for a missing
     * user makes that case measurably faster, and a stopwatch then answers the same question the
     * registration endpoint refuses to.
     */
    @Transactional
    public Tokens login(String rawEmail, String password) {
        String email = normalise(rawEmail);
        Optional<UserEntity> found = users.findByEmail(email);

        if (found.isEmpty()) {
            passwords.matches(password, DUMMY_HASH);
            throw new InvalidCredentialsException("Email or password is not correct");
        }
        UserEntity user = found.get();
        if (!passwords.matches(password, user.getPasswordHash())) {
            throw new InvalidCredentialsException("Email or password is not correct");
        }
        return issueTokensFor(user);
    }

    /**
     * Exchange a refresh token for a new pair, revoking the old one.
     *
     * <p>{@code noRollbackFor} is load-bearing, not tidiness. The reuse branch below revokes every
     * session the user has and then throws - and a thrown exception rolls the transaction back by
     * default, which would undo the revocations and leave the stolen token working. The security
     * response has to survive the rejection that triggers it.
     */
    @Transactional(noRollbackFor = InvalidCredentialsException.class)
    public Tokens refresh(String refreshToken) {
        Instant now = clock.instant();
        RefreshTokenEntity stored = refreshTokens
                .findByTokenHash(TokenHash.hash(refreshToken))
                .orElseThrow(() -> new InvalidCredentialsException("That session has ended. Please log in again."));

        if (stored.isRevoked()) {
            // A revoked token presented again means somebody has a copy. Which of the two holders
            // is the real user cannot be known, so both are logged out.
            log.warn("a revoked refresh token was presented; revoking every session for that user");
            refreshTokens.findByUserId(stored.getUserId()).forEach(token -> token.revoke(now));
            throw new InvalidCredentialsException("That session has ended. Please log in again.");
        }
        if (!stored.isUsable(now)) {
            throw new InvalidCredentialsException("That session has ended. Please log in again.");
        }

        stored.revoke(now);
        UserEntity user =
                users.findById(stored.getUserId()).orElseThrow(() -> new NotFoundException("No such account"));
        return issueTokensFor(user);
    }

    /** Log out of one session. */
    @Transactional
    public void logout(String refreshToken) {
        refreshTokens.findByTokenHash(TokenHash.hash(refreshToken)).ifPresent(token -> token.revoke(clock.instant()));
    }

    private Tokens issueTokensFor(UserEntity user) {
        Instant now = clock.instant();
        String refresh = TokenHash.newToken();
        refreshTokens.save(new RefreshTokenEntity(user.getId(), TokenHash.hash(refresh), now.plus(REFRESH_LIFETIME)));
        return new Tokens(
                accessTokens.issue(user.getId(), user.getEmail(), user.getRole(), now),
                refresh,
                accessTokens.lifetimeSeconds(),
                user.isEmailVerified());
    }

    private static String normalise(String email) {
        return email == null ? "" : email.trim().toLowerCase(Locale.ROOT);
    }

    /**
     * A real BCrypt hash of a value nobody knows, used so that logging in with an unknown address
     * costs the same as logging in with a known one.
     */
    private static final String DUMMY_HASH = "$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy";

    /** What a successful login hands back. */
    public record Tokens(String accessToken, String refreshToken, long expiresInSeconds, boolean emailVerified) {}
}
