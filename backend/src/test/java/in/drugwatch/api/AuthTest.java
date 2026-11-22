package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import in.drugwatch.api.auth.domain.AuthService;
import in.drugwatch.api.auth.domain.InvalidCredentialsException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import javax.sql.DataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

/**
 * Registration, login, refresh and verification.
 *
 * <p>Most of these are about what the API refuses to reveal. A site about the medicines people
 * take is one where "does this person have an account here" is itself private.
 */
@SpringBootTest
@Import({TestDatabase.class, AuthTest.MovableClock.class})
class AuthTest {

    /** A clock the tests can move, so expiry is testable without waiting thirty days. */
    @TestConfiguration(proxyBeanMethods = false)
    static class MovableClock {
        static Instant now = Instant.parse("2026-11-21T10:00:00Z");

        @Bean
        @Primary
        Clock testClock() {
            return new Clock() {
                @Override
                public ZoneOffset getZone() {
                    return ZoneOffset.UTC;
                }

                @Override
                public Clock withZone(java.time.ZoneId zone) {
                    return this;
                }

                @Override
                public Instant instant() {
                    return now;
                }
            };
        }
    }

    @Autowired
    AuthService auth;

    @Autowired
    DataSource dataSource;

    @MockitoBean
    JavaMailSender mail;

    @BeforeEach
    void reset() {
        MovableClock.now = Instant.parse("2026-11-21T10:00:00Z");
        JdbcClient.create(dataSource).sql("DELETE FROM app.users").update();
    }

    private JdbcClient sql() {
        return JdbcClient.create(dataSource);
    }

    private String verificationTokenFromEmail() {
        var captor = org.mockito.ArgumentCaptor.forClass(SimpleMailMessage.class);
        org.mockito.Mockito.verify(mail, org.mockito.Mockito.atLeastOnce()).send(captor.capture());
        String body = captor.getAllValues().getLast().getText();
        return body.substring(body.indexOf("token=") + "token=".length())
                .split("\\s")[0]
                .trim();
    }

    // ------------------------------------------------------------------ registration

    @Test
    void registering_creates_an_unverified_account() {
        auth.register("Reader@Example.com", "a-long-enough-password");

        var stored = sql().sql("SELECT email, email_verified FROM app.users")
                .query((row, number) -> row.getString("email") + "/" + row.getBoolean("email_verified"))
                .single();
        // Lower-cased on the way in, and unverified until the link is used.
        assertThat(stored).isEqualTo("reader@example.com/false");
    }

    @Test
    void the_password_is_never_stored() {
        auth.register("reader@example.com", "a-long-enough-password");

        String hash = sql().sql("SELECT password_hash FROM app.users")
                .query(String.class)
                .single();
        assertThat(hash).doesNotContain("a-long-enough-password");
        assertThat(hash).startsWith("$2"); // BCrypt
    }

    @Test
    void registering_an_address_that_already_exists_creates_nothing_and_does_not_say_so() {
        // The oracle this closes: a public endpoint that answers "is this person registered here"
        // for any address anybody cares to type.
        auth.register("reader@example.com", "a-long-enough-password");
        auth.register("reader@example.com", "a-completely-different-password");

        assertThat(sql().sql("SELECT count(*) FROM app.users")
                        .query(Integer.class)
                        .single())
                .isEqualTo(1);
    }

    @Test
    void the_owner_of_an_existing_address_is_told_somebody_tried() {
        auth.register("reader@example.com", "a-long-enough-password");
        auth.register("reader@example.com", "another-long-password");

        var captor = org.mockito.ArgumentCaptor.forClass(SimpleMailMessage.class);
        org.mockito.Mockito.verify(mail, org.mockito.Mockito.atLeast(2)).send(captor.capture());
        // The second email goes to the address, not to whoever made the attempt.
        SimpleMailMessage second = captor.getAllValues().getLast();
        assertThat(second.getSubject()).contains("tried to register");
        assertThat(second.getText()).contains("Nothing has changed on your account");
    }

    // ------------------------------------------------------------------ verification

    @Test
    void a_verification_link_confirms_the_address() {
        auth.register("reader@example.com", "a-long-enough-password");

        auth.verifyEmail(verificationTokenFromEmail());

        assertThat(sql().sql("SELECT email_verified FROM app.users")
                        .query(Boolean.class)
                        .single())
                .isTrue();
    }

    @Test
    void a_verification_link_works_once() {
        auth.register("reader@example.com", "a-long-enough-password");
        String token = verificationTokenFromEmail();
        auth.verifyEmail(token);

        // A link that keeps working is a credential sitting in an inbox.
        assertThatThrownBy(() -> auth.verifyEmail(token)).isInstanceOf(InvalidCredentialsException.class);
    }

    @Test
    void a_verification_link_expires() {
        auth.register("reader@example.com", "a-long-enough-password");
        String token = verificationTokenFromEmail();

        MovableClock.now = MovableClock.now.plus(Duration.ofHours(25));

        assertThatThrownBy(() -> auth.verifyEmail(token)).isInstanceOf(InvalidCredentialsException.class);
    }

    @Test
    void the_verification_token_is_stored_only_as_a_hash() {
        auth.register("reader@example.com", "a-long-enough-password");
        String token = verificationTokenFromEmail();

        String stored = sql().sql("SELECT token_hash FROM app.email_verifications")
                .query(String.class)
                .single();
        assertThat(stored).isNotEqualTo(token).hasSize(64); // SHA-256 hex
    }

    // ------------------------------------------------------------------ login

    @Test
    void logging_in_returns_an_access_token_and_a_refresh_token() {
        auth.register("reader@example.com", "a-long-enough-password");

        var tokens = auth.login("reader@example.com", "a-long-enough-password");

        assertThat(tokens.accessToken()).isNotBlank();
        assertThat(tokens.refreshToken()).isNotBlank();
        assertThat(tokens.expiresInSeconds()).isEqualTo(900); // 15 minutes
        assertThat(tokens.emailVerified()).isFalse();
    }

    @Test
    void the_wrong_password_and_an_unknown_address_fail_identically() {
        auth.register("reader@example.com", "a-long-enough-password");

        String wrongPassword = messageFrom(() -> auth.login("reader@example.com", "not-the-password"));
        String unknownEmail = messageFrom(() -> auth.login("nobody@example.com", "a-long-enough-password"));

        assertThat(wrongPassword).isEqualTo(unknownEmail);
    }

    @Test
    void the_email_is_matched_regardless_of_case() {
        auth.register("reader@example.com", "a-long-enough-password");

        assertThat(auth.login("READER@Example.COM", "a-long-enough-password").accessToken())
                .isNotBlank();
    }

    @Test
    void the_refresh_token_is_stored_only_as_a_hash() {
        auth.register("reader@example.com", "a-long-enough-password");
        var tokens = auth.login("reader@example.com", "a-long-enough-password");

        String stored = sql().sql("SELECT token_hash FROM app.refresh_tokens")
                .query(String.class)
                .single();
        assertThat(stored).isNotEqualTo(tokens.refreshToken()).hasSize(64);
    }

    // ------------------------------------------------------------------ refresh

    @Test
    void a_refresh_token_can_be_exchanged_for_a_new_pair() {
        auth.register("reader@example.com", "a-long-enough-password");
        var first = auth.login("reader@example.com", "a-long-enough-password");

        var second = auth.refresh(first.refreshToken());

        assertThat(second.refreshToken()).isNotEqualTo(first.refreshToken());
    }

    @Test
    void a_refresh_token_works_only_once() {
        auth.register("reader@example.com", "a-long-enough-password");
        var first = auth.login("reader@example.com", "a-long-enough-password");
        auth.refresh(first.refreshToken());

        assertThatThrownBy(() -> auth.refresh(first.refreshToken())).isInstanceOf(InvalidCredentialsException.class);
    }

    @Test
    void reusing_a_revoked_token_ends_every_session_that_user_has() {
        // A revoked token presented again means somebody has a copy. Which of the two holders is
        // the real user cannot be known, so both are logged out.
        auth.register("reader@example.com", "a-long-enough-password");
        var first = auth.login("reader@example.com", "a-long-enough-password");
        var second = auth.refresh(first.refreshToken()); // first is now revoked

        assertThatThrownBy(() -> auth.refresh(first.refreshToken())).isInstanceOf(InvalidCredentialsException.class);

        // The still-valid token from the legitimate refresh is revoked too.
        assertThatThrownBy(() -> auth.refresh(second.refreshToken())).isInstanceOf(InvalidCredentialsException.class);
    }

    @Test
    void a_refresh_token_expires() {
        auth.register("reader@example.com", "a-long-enough-password");
        var tokens = auth.login("reader@example.com", "a-long-enough-password");

        MovableClock.now = MovableClock.now.plus(Duration.ofDays(31));

        assertThatThrownBy(() -> auth.refresh(tokens.refreshToken())).isInstanceOf(InvalidCredentialsException.class);
    }

    @Test
    void logging_out_ends_that_session() {
        auth.register("reader@example.com", "a-long-enough-password");
        var tokens = auth.login("reader@example.com", "a-long-enough-password");

        auth.logout(tokens.refreshToken());

        assertThatThrownBy(() -> auth.refresh(tokens.refreshToken())).isInstanceOf(InvalidCredentialsException.class);
    }

    @Test
    void an_invented_refresh_token_is_refused_without_saying_why() {
        assertThat(messageFrom(() -> auth.refresh("not-a-real-token"))).contains("Please log in again");
    }

    private static String messageFrom(Runnable action) {
        try {
            action.run();
            throw new AssertionError("expected this to fail");
        } catch (InvalidCredentialsException expected) {
            return expected.getMessage();
        }
    }
}
