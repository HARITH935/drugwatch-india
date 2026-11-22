package in.drugwatch.api.watchlist.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

/** The two tables the watchlist owns, and their repositories. */
final class WatchlistEntities {
    private WatchlistEntities() {}
}

@Entity
@Table(name = "watchlist_items")
class WatchlistItemEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    /** What the user typed, kept so it can be shown back unchanged. */
    @Column(nullable = false)
    private String term;

    /** The normalised form matching uses. */
    @Column(name = "term_norm", nullable = false)
    private String termNorm;

    /**
     * Alert months at or before this are never notified: the archive's latest month when the
     * watch was created. See V2__watchlist_baseline.sql.
     */
    @Column(name = "since_alert_month", nullable = false)
    private String sinceAlertMonth;

    /**
     * Written by the application rather than left to the column default.
     *
     * <p>With {@code insertable = false} the saved object never learns the value the database
     * generated, so the API answered {@code "createdAt": null} for a field it advertises. Setting
     * it here gives one source of truth for rows the application creates; the column default
     * stays as a backstop for anything inserted directly.
     */
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected WatchlistItemEntity() {}

    WatchlistItemEntity(Long userId, String term, String termNorm, String sinceAlertMonth, Instant createdAt) {
        this.userId = userId;
        this.term = term;
        this.termNorm = termNorm;
        this.sinceAlertMonth = sinceAlertMonth;
        this.createdAt = createdAt;
    }

    Long getId() {
        return id;
    }

    Long getUserId() {
        return userId;
    }

    String getTerm() {
        return term;
    }

    String getTermNorm() {
        return termNorm;
    }

    String getSinceAlertMonth() {
        return sinceAlertMonth;
    }

    Instant getCreatedAt() {
        return createdAt;
    }
}

@Entity
@Table(name = "alert_notifications")
class AlertNotificationEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "watchlist_item_id", nullable = false)
    private Long watchlistItemId;

    @Column(name = "alert_month", nullable = false)
    private String alertMonth;

    @Column(name = "findings_matched", nullable = false)
    private int findingsMatched;

    @Column(name = "sent_at", nullable = false, insertable = false, updatable = false)
    private Instant sentAt;

    protected AlertNotificationEntity() {}

    AlertNotificationEntity(Long userId, Long watchlistItemId, String alertMonth, int findingsMatched) {
        this.userId = userId;
        this.watchlistItemId = watchlistItemId;
        this.alertMonth = alertMonth;
        this.findingsMatched = findingsMatched;
    }
}

interface WatchlistItemRepository extends JpaRepository<WatchlistItemEntity, Long> {
    List<WatchlistItemEntity> findByUserIdOrderByCreatedAtDesc(Long userId);

    Optional<WatchlistItemEntity> findByIdAndUserId(Long id, Long userId);

    boolean existsByUserIdAndTermNorm(Long userId, String termNorm);

    long countByUserId(Long userId);
}

interface AlertNotificationRepository extends JpaRepository<AlertNotificationEntity, Long> {

    /**
     * Every watch that is due a notification, with the user's address.
     *
     * <p>Written as one query rather than a loop over watches so that "due" is decided in the
     * database: a verified user, an alert month after the watch's baseline, at least one matching
     * finding, and nothing already recorded for that pair. The {@code NOT EXISTS} and the UNIQUE
     * constraint are belt and braces - the query avoids the work, the constraint makes a duplicate
     * impossible even if two runs overlap.
     *
     * <p>{@code \y} is a word boundary, so "ace" cannot match "Paracetamol".
     */
    @Query(value = """
                    SELECT w.id AS item_id, w.user_id, u.email, w.term, m.alert_month, m.findings
                    FROM app.watchlist_items w
                    JOIN app.users u ON u.id = w.user_id
                    JOIN LATERAL (
                        SELECT f.alert_month, count(*) AS findings
                        FROM gold.fact_nsq_sample f
                        JOIN gold.dim_drug d ON d.drug_id = f.drug_id
                        WHERE f.alert_month > w.since_alert_month
                          AND (d.product_name ~* ('\\y' || w.term_norm || '\\y')
                               OR coalesce(d.generic_name, '') ~* ('\\y' || w.term_norm || '\\y'))
                        GROUP BY f.alert_month
                    ) m ON true
                    WHERE u.email_verified
                      AND NOT EXISTS (
                        SELECT 1 FROM app.alert_notifications n
                        WHERE n.watchlist_item_id = w.id AND n.alert_month = m.alert_month)
                    ORDER BY m.alert_month, w.id
                    """, nativeQuery = true)
    List<Object[]> findDueNotifications();
}
