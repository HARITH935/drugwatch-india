package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import in.drugwatch.api.shared.NotFoundException;
import in.drugwatch.api.watchlist.domain.WatchlistNotifier;
import in.drugwatch.api.watchlist.domain.WatchlistService;
import javax.sql.DataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;

/**
 * The watchlist and its notifications.
 *
 * <p>The tests that matter are the ones about restraint: not emailing the archive at somebody who
 * just signed up, not emailing an address nobody confirmed, and not emailing the same thing twice.
 */
@SpringBootTest
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
class WatchlistTest {

    @Autowired
    WatchlistService watchlist;

    @Autowired
    WatchlistNotifier notifier;

    @Autowired
    DataSource dataSource;

    @MockitoBean
    JavaMailSender mail;

    private JdbcClient sql() {
        return JdbcClient.create(dataSource);
    }

    @BeforeEach
    void clearAccounts() {
        sql().sql("DELETE FROM app.users").update();
    }

    /** An account. The fixture's newest alert month is 2026-03. */
    private long user(String email, boolean verified) {
        return sql().sql("""
                        INSERT INTO app.users (email, password_hash, email_verified)
                        VALUES (?, 'hash', ?) RETURNING id
                        """).params(email, verified).query(Long.class).single();
    }

    // ------------------------------------------------------------------ managing watches

    @Test
    void a_watch_records_the_archives_latest_month_as_its_baseline() {
        long reader = user("reader@example.com", true);

        var watch = watchlist.add(reader, "Zyntophil");

        // The fixture's newest alert month. Anything at or before this is never notified.
        assertThat(watch.notifiedFromAfter()).isEqualTo("2026-03");
    }

    @Test
    void the_same_term_cannot_be_watched_twice() {
        long reader = user("reader@example.com", true);
        watchlist.add(reader, "Zyntophil");

        // Typed differently, same term: re-adding must not double the emails.
        assertThatThrownBy(() -> watchlist.add(reader, "  zyntophil  "))
                .isInstanceOf(WatchlistService.InvalidWatchException.class)
                .hasMessageContaining("already watching");
    }

    @Test
    void a_term_that_cannot_be_matched_is_refused_with_an_explanation() {
        long reader = user("reader@example.com", true);

        assertThatThrownBy(() -> watchlist.add(reader, "ab"))
                .isInstanceOf(WatchlistService.InvalidWatchException.class)
                .hasMessageContaining("3 to 100 characters");
    }

    @Test
    void watches_are_listed_for_their_owner_only() {
        long first = user("a@example.com", true);
        long second = user("b@example.com", true);
        watchlist.add(first, "Zyntophil");
        watchlist.add(second, "Brivolax");

        assertThat(watchlist.list(first))
                .extracting(WatchlistService.Watch::term)
                .containsExactly("Zyntophil");
        assertThat(watchlist.list(second))
                .extracting(WatchlistService.Watch::term)
                .containsExactly("Brivolax");
    }

    @Test
    void one_user_cannot_delete_another_users_watch() {
        // Scoped by user as well as id. Without that, anybody could delete anybody's watch by
        // guessing a number - and "not yours" is reported as "does not exist", because the
        // difference is itself information.
        long owner = user("owner@example.com", true);
        long other = user("other@example.com", true);
        var watch = watchlist.add(owner, "Zyntophil");

        assertThatThrownBy(() -> watchlist.remove(other, watch.id())).isInstanceOf(NotFoundException.class);
        assertThat(watchlist.list(owner)).hasSize(1);
    }

    @Test
    void a_watch_can_be_removed_by_its_owner() {
        long reader = user("reader@example.com", true);
        var watch = watchlist.add(reader, "Zyntophil");

        watchlist.remove(reader, watch.id());

        assertThat(watchlist.list(reader)).isEmpty();
    }

    // ------------------------------------------------------------------ notifications

    /** Pretend the watch predates the archive, so its matches become notifiable. */
    private void backdate(long watchId, String sinceMonth) {
        sql().sql("UPDATE app.watchlist_items SET since_alert_month = ? WHERE id = ?")
                .params(sinceMonth, watchId)
                .update();
    }

    @Test
    void adding_a_watch_does_not_email_the_whole_archive() {
        // The point of the baseline. Without it, adding "Zyntophil" would match findings across
        // the archive's months and send an email for each - about a hundred in production, which
        // is indistinguishable from spam and would get the sending domain blocked.
        long reader = user("reader@example.com", true);
        watchlist.add(reader, "Zyntophil");

        assertThat(notifier.runOnce()).isZero();
        Mockito.verifyNoInteractions(mail);
    }

    @Test
    void a_new_alert_month_notifies_a_matching_watch() {
        long reader = user("reader@example.com", true);
        var watch = watchlist.add(reader, "Zyntophil");
        backdate(watch.id(), "2025-01"); // now 2025-11, 2026-02 and 2026-03 are "new"

        int sent = notifier.runOnce();

        assertThat(sent).isPositive();
        var captor = ArgumentCaptor.forClass(SimpleMailMessage.class);
        Mockito.verify(mail, Mockito.atLeastOnce()).send(captor.capture());
        assertThat(captor.getValue().getSubject()).contains("Zyntophil").contains("CDSCO alert");
    }

    @Test
    void an_unverified_address_is_never_written_to() {
        // Decision E. Otherwise anybody can register with a stranger's address, add watch terms,
        // and have the site email that stranger about medicine alerts under CDSCO's name.
        long reader = user("unverified@example.com", false);
        var watch = watchlist.add(reader, "Zyntophil");
        backdate(watch.id(), "2025-01");

        assertThat(notifier.runOnce()).isZero();
        Mockito.verifyNoInteractions(mail);
    }

    @Test
    void the_same_month_is_never_notified_twice() {
        long reader = user("reader@example.com", true);
        var watch = watchlist.add(reader, "Zyntophil");
        backdate(watch.id(), "2025-01");

        int first = notifier.runOnce();
        int second = notifier.runOnce();

        assertThat(first).isPositive();
        assertThat(second).isZero();
    }

    @Test
    void what_was_sent_is_recorded() {
        long reader = user("reader@example.com", true);
        var watch = watchlist.add(reader, "Zyntophil");
        backdate(watch.id(), "2025-01");
        notifier.runOnce();

        var rows = sql().sql("""
                        SELECT alert_month, findings_matched FROM app.alert_notifications
                        WHERE watchlist_item_id = ? ORDER BY alert_month
                        """)
                .param(watch.id())
                .query((row, number) -> row.getString("alert_month") + "/" + row.getInt("findings_matched"))
                .list();

        assertThat(rows).isNotEmpty();
        assertThat(rows).allSatisfy(entry -> assertThat(entry).matches("\\d{4}-\\d{2}/[1-9]\\d*"));
    }

    @Test
    void a_term_only_matches_whole_words() {
        // "oral" must not match "Brivolax Oral Suspension" via a substring of something else, and
        // more importantly a short fragment must not match everything. The fixture has
        // "Calmirex Cough Syrup"; "cal" is not a word in it.
        long reader = user("reader@example.com", true);
        var watch = watchlist.add(reader, "cal");
        backdate(watch.id(), "2020-01");

        assertThat(notifier.runOnce()).isZero();
    }

    @Test
    void the_email_says_a_finding_is_about_one_batch() {
        long reader = user("reader@example.com", true);
        var watch = watchlist.add(reader, "Zyntophil");
        backdate(watch.id(), "2025-01");
        notifier.runOnce();

        var captor = ArgumentCaptor.forClass(SimpleMailMessage.class);
        Mockito.verify(mail, Mockito.atLeastOnce()).send(captor.capture());
        String body = captor.getValue().getText();

        assertThat(body).contains("one specific batch");
        assertThat(body).contains("not a guarantee that it is safe");
        assertThat(body).contains("Not medical advice. Data from CDSCO public alerts.");
        // And a way out of it, in every email.
        assertThat(body).contains("/watchlist");
    }

    @Test
    void two_users_watching_the_same_term_both_get_told() {
        long first = user("a@example.com", true);
        long second = user("b@example.com", true);
        var firstWatch = watchlist.add(first, "Zyntophil");
        var secondWatch = watchlist.add(second, "Zyntophil");
        backdate(firstWatch.id(), "2025-01");
        backdate(secondWatch.id(), "2025-01");

        notifier.runOnce();

        var captor = ArgumentCaptor.forClass(SimpleMailMessage.class);
        Mockito.verify(mail, Mockito.atLeastOnce()).send(captor.capture());
        assertThat(captor.getAllValues())
                .extracting(message -> message.getTo()[0])
                .contains("a@example.com", "b@example.com");
    }
}
