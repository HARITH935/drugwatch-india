package in.drugwatch.api.watchlist.domain;

import in.drugwatch.api.shared.PublicNotes;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Sends a watchlist email when a new alert month names something somebody is watching.
 *
 * <p><b>The API polls; Airflow does not call the API.</b> Phase 9 decision D. The pipeline's job
 * ends when the warehouse is correct, and a webhook between them would need a shared secret, a
 * retry policy and an endpoint that must be protected - for a job whose trigger is "is there a
 * month we have not told anybody about". A daily query answers that with no new coupling.
 *
 * <p><b>A row is written before the email is sent.</b> The UNIQUE constraint on (watch, alert
 * month) then makes a second send impossible - two overlapping runs, a retry, or a redeploy
 * mid-send all collide with the database rather than emailing somebody twice. The cost is the
 * opposite failure: if the row commits and the send fails, that notification is lost rather than
 * retried. For a monthly digest about medicine alerts, one missed email is better than an
 * unbounded number of duplicates, and the next month's alert arrives anyway.
 *
 * <p>Only <b>verified</b> addresses are ever written to (decision E) - enforced in the query, so
 * an unverified account cannot be mailed even by a bug here.
 */
@Component
public class WatchlistNotifier {

    private static final Logger log = LoggerFactory.getLogger(WatchlistNotifier.class);

    private final AlertNotificationRepository notifications;
    private final JavaMailSender mail;
    private final String from;
    private final String siteUrl;

    WatchlistNotifier(
            AlertNotificationRepository notifications,
            JavaMailSender mail,
            @Value("${drugwatch.mail.from}") String from,
            @Value("${drugwatch.site-url}") String siteUrl) {
        this.notifications = notifications;
        this.mail = mail;
        this.from = from;
        this.siteUrl = siteUrl;
    }

    /**
     * Once a day. CDSCO publishes monthly, so hourly would be 720 pointless queries a month and
     * weekly could sit on an alert for six days.
     */
    @Scheduled(cron = "${drugwatch.watchlist.cron:0 30 9 * * *}")
    public void sendDueNotifications() {
        int sent = runOnce();
        if (sent > 0) {
            log.info("sent {} watchlist notification(s)", sent);
        }
    }

    /** Separated from the schedule so a test can run it without waiting for a cron tick. */
    @Transactional
    public int runOnce() {
        var due = notifications.findDueNotifications();
        int sent = 0;
        for (Object[] row : due) {
            Long itemId = ((Number) row[0]).longValue();
            Long userId = ((Number) row[1]).longValue();
            String email = (String) row[2];
            String term = (String) row[3];
            String alertMonth = (String) row[4];
            int findings = ((Number) row[5]).intValue();

            // Claim it first. If this throws on the unique constraint, another run got there.
            notifications.saveAndFlush(new AlertNotificationEntity(userId, itemId, alertMonth, findings));
            send(email, term, alertMonth, findings);
            sent++;
        }
        return sent;
    }

    private void send(String email, String term, String alertMonth, int findings) {
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(email);
        message.setSubject("%s: %d batch%s reported in the %s CDSCO alert"
                .formatted(term, findings, findings == 1 ? "" : "es", alertMonth));
        message.setText("""
                You are watching "%s".

                The CDSCO alert for %s reports %d batch%s whose medicine name matches it.

                See the details, including the batch numbers and a link to the original CDSCO
                document: %s/drugs/search?q=%s

                %s

                Each finding applies to one specific batch that a laboratory tested - not to the
                medicine in general, and not to the company that made it. A batch not appearing in
                an alert is not a guarantee that it is safe.

                Stop watching this: %s/watchlist
                """.formatted(
                        term,
                        alertMonth,
                        findings,
                        findings == 1 ? "" : "es",
                        siteUrl,
                        java.net.URLEncoder.encode(term, java.nio.charset.StandardCharsets.UTF_8),
                        PublicNotes.DISCLAIMER,
                        siteUrl));
        try {
            mail.send(message);
        } catch (MailException failure) {
            // Logged without the address, and not retried: see the note on this class.
            log.error("could not send a watchlist notification for {}", alertMonth, failure);
        }
    }
}
