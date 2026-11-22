package in.drugwatch.api.auth.domain;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Component;

/**
 * The two emails {@code auth} sends.
 *
 * <p>A failure to send is logged and swallowed, which is a deliberate choice rather than
 * carelessness: if the mail server is down, a registration that has already created the account
 * must not report failure and invite the person to register again - the second attempt would hit
 * the "already registered" path and they would be stuck. The verification link can be resent.
 *
 * <p>Neither message contains CDSCO data, so neither is affected by ADR 0003.
 */
@Component
class AuthMailer {

    private static final Logger log = LoggerFactory.getLogger(AuthMailer.class);

    private final JavaMailSender mail;
    private final String from;
    private final String siteUrl;

    AuthMailer(
            JavaMailSender mail,
            @Value("${drugwatch.mail.from}") String from,
            @Value("${drugwatch.site-url}") String siteUrl) {
        this.mail = mail;
        this.from = from;
        this.siteUrl = siteUrl;
    }

    void sendVerification(String email, String token) {
        send(email, "Confirm your email address", """
                Someone asked to create a DrugWatch India account with this address.

                Confirm it to finish: %s/verify?token=%s

                The link works once and expires in 24 hours. If this was not you, ignore this
                email - no account can be used until the address is confirmed.
                """.formatted(siteUrl, token));
    }

    /**
     * Sent when somebody tries to register an address that already has an account.
     *
     * <p>This is what lets the registration endpoint answer identically either way. The person who
     * owns the address learns something useful; whoever made the attempt learns nothing.
     */
    void sendAlreadyRegistered(String email) {
        send(email, "Someone tried to register with your address", """
                Someone just tried to create a DrugWatch India account using this address, which
                already has one.

                If that was you, log in instead: %s/login
                If it was not, no action is needed. Nothing has changed on your account.
                """.formatted(siteUrl));
    }

    private void send(String to, String subject, String body) {
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(to);
        message.setSubject(subject);
        message.setText(body);
        try {
            mail.send(message);
        } catch (MailException failure) {
            // Logged without the address: a log line is not the place for somebody's email.
            log.error("could not send '{}'", subject, failure);
        }
    }
}
