package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.jdbc.Sql;

/**
 * The migration produces the constraints the design depends on.
 *
 * <p>These are not "does CREATE TABLE work" tests. Each one checks a rule that the application
 * would otherwise have to remember, in the one place that cannot forget it. A constraint that is
 * only enforced in Java is enforced until the second code path.
 */
@SpringBootTest
@Import(TestDatabase.class)
@Sql(statements = "DELETE FROM app.users", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
class AppSchemaTest {

    @Autowired
    DataSource dataSource;

    private JdbcClient sql() {
        return JdbcClient.create(dataSource);
    }

    private long insertUser(String email) {
        return sql().sql("""
                        INSERT INTO app.users (email, password_hash) VALUES (?, 'hash') RETURNING id
                        """).param(email).query(Long.class).single();
    }

    @Test
    void flyway_created_every_app_table() {
        var tables = sql().sql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'app'")
                .query(String.class)
                .list();

        assertThat(tables)
                .contains("users", "email_verifications", "watchlist_items", "alert_notifications", "refresh_tokens");
    }

    @Test
    void the_migration_is_recorded_so_it_runs_exactly_once() {
        var applied = sql().sql("SELECT count(*) FROM app.flyway_schema_history WHERE success")
                .query(Integer.class)
                .single();

        assertThat(applied).isPositive();
    }

    @Test
    void nothing_was_created_outside_the_app_schema() {
        // Flyway owns `app`; dbt owns `gold`. A migration that leaked a table into `public` would
        // be the first step towards two tools editing the same schema.
        var elsewhere = sql().sql("""
                        SELECT count(*) FROM information_schema.tables
                        WHERE table_schema NOT IN ('app', 'information_schema', 'pg_catalog')
                        """).query(Integer.class).single();

        assertThat(elsewhere).isZero();
    }

    // ------------------------------------------------------------------ the rules that matter

    @Test
    void the_same_alert_month_cannot_be_notified_twice() {
        // The reason alert_notifications exists. A retry after a half-finished run, two schedulers
        // overlapping, or a redeploy mid-send must collide with a constraint rather than email
        // somebody twice about the same alert month.
        long user = insertUser("watcher@example.com");
        long item = sql().sql("""
                        INSERT INTO app.watchlist_items (user_id, term, term_norm)
                        VALUES (?, 'Telmisartan', 'telmisartan') RETURNING id
                        """).param(user).query(Long.class).single();

        insertNotification(user, item, "2026-03");

        assertThatThrownBy(() -> insertNotification(user, item, "2026-03"))
                .hasMessageContaining("alert_notifications_once");
    }

    @Test
    void a_different_alert_month_is_a_different_notification() {
        long user = insertUser("watcher2@example.com");
        long item = sql().sql("""
                        INSERT INTO app.watchlist_items (user_id, term, term_norm)
                        VALUES (?, 'Telmisartan', 'telmisartan') RETURNING id
                        """).param(user).query(Long.class).single();

        insertNotification(user, item, "2026-03");
        insertNotification(user, item, "2026-04");

        assertThat(sql().sql("SELECT count(*) FROM app.alert_notifications WHERE user_id = ?")
                        .param(user)
                        .query(Integer.class)
                        .single())
                .isEqualTo(2);
    }

    @Test
    void an_email_must_be_stored_lower_case() {
        // Without this, "A@b.com" and "a@b.com" become two accounts and the unique index on email
        // stops meaning anything.
        assertThatThrownBy(() -> insertUser("Mixed@Example.com")).hasMessageContaining("users_email_check");
    }

    @Test
    void the_same_email_cannot_register_twice() {
        insertUser("once@example.com");
        assertThatThrownBy(() -> insertUser("once@example.com")).hasMessageContaining("users_email_key");
    }

    @Test
    void a_new_account_has_not_verified_its_email() {
        // Decision E: no notification may go to an address nobody has confirmed, so the column
        // must default to false rather than relying on the registration code to set it.
        long user = insertUser("fresh@example.com");

        assertThat(sql().sql("SELECT email_verified FROM app.users WHERE id = ?")
                        .param(user)
                        .query(Boolean.class)
                        .single())
                .isFalse();
    }

    @Test
    void the_same_term_cannot_be_watched_twice_by_one_user() {
        long user = insertUser("dup@example.com");
        addWatch(user, "Telmisartan", "telmisartan");

        // Re-adding the same medicine, typed differently, must not double the emails.
        assertThatThrownBy(() -> addWatch(user, "telmisartan", "telmisartan"))
                .hasMessageContaining("watchlist_items_unique_per_user");
    }

    @Test
    void two_users_may_watch_the_same_term() {
        long first = insertUser("a@example.com");
        long second = insertUser("b@example.com");

        addWatch(first, "Telmisartan", "telmisartan");
        addWatch(second, "Telmisartan", "telmisartan");

        assertThat(sql().sql("SELECT count(*) FROM app.watchlist_items WHERE term_norm = 'telmisartan'")
                        .query(Integer.class)
                        .single())
                .isEqualTo(2);
    }

    @Test
    void a_watch_term_must_be_long_enough_to_mean_something() {
        // A one- or two-letter term would match most of the archive and email the user every
        // month, which is indistinguishable from spam from the reader's side.
        long user = insertUser("short@example.com");

        assertThatThrownBy(() -> addWatch(user, "ab", "ab")).hasMessageContaining("watchlist_items_term_check");
    }

    @Test
    void deleting_a_user_removes_everything_that_belongs_to_them() {
        // An account deletion that left watch terms behind would keep emailing a deleted account.
        long user = insertUser("leaving@example.com");
        long item = addWatch(user, "Telmisartan", "telmisartan");
        insertNotification(user, item, "2026-03");

        sql().sql("DELETE FROM app.users WHERE id = ?").param(user).update();

        assertThat(sql().sql("SELECT count(*) FROM app.watchlist_items WHERE user_id = ?")
                        .param(user)
                        .query(Integer.class)
                        .single())
                .isZero();
        assertThat(sql().sql("SELECT count(*) FROM app.alert_notifications WHERE user_id = ?")
                        .param(user)
                        .query(Integer.class)
                        .single())
                .isZero();
    }

    @Test
    void an_alert_month_must_look_like_an_alert_month() {
        // The column joins against gold.fact_nsq_sample.alert_month, which is 'YYYY-MM'. A row
        // holding 'March 2026' would simply never match and nobody would be told why.
        long user = insertUser("month@example.com");
        long item = addWatch(user, "Telmisartan", "telmisartan");

        assertThatThrownBy(() -> insertNotification(user, item, "March 2026"))
                .hasMessageContaining("alert_notifications_alert_month_check");
    }

    private long addWatch(long user, String term, String normalised) {
        return sql().sql("""
                        INSERT INTO app.watchlist_items (user_id, term, term_norm) VALUES (?, ?, ?) RETURNING id
                        """).params(user, term, normalised).query(Long.class).single();
    }

    private void insertNotification(long user, long item, String alertMonth) {
        sql().sql("""
                        INSERT INTO app.alert_notifications (user_id, watchlist_item_id, alert_month, findings_matched)
                        VALUES (?, ?, ?, 1)
                        """).params(user, item, alertMonth).update();
    }
}
