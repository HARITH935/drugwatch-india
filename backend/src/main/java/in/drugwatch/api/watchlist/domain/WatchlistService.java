package in.drugwatch.api.watchlist.domain;

import in.drugwatch.api.shared.NotFoundException;
import java.util.List;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Adding, listing and removing watches. */
@Service
public class WatchlistService {

    /**
     * A ceiling per account. Not an arbitrary limit: every watch is a monthly email and a row in a
     * query that runs for every user, so an account with a thousand terms is both a mail problem
     * and a load problem - and "watch everything" is what the drug pages are for.
     */
    static final int MAXIMUM_WATCHES = 50;

    private final WatchlistItemRepository items;
    private final JdbcClient jdbc;
    private final java.time.Clock clock;

    WatchlistService(WatchlistItemRepository items, DataSource dataSource, java.time.Clock clock) {
        this.items = items;
        this.jdbc = JdbcClient.create(dataSource);
        this.clock = clock;
    }

    @Transactional
    public Watch add(Long userId, String typedTerm) {
        String normalised = WatchTerm.normalise(typedTerm)
                .orElseThrow(() -> new InvalidWatchException(
                        "A watch must be 3 to 100 characters of letters, digits, spaces, hyphens or"
                                + " apostrophes - it is matched against the medicine name printed in the"
                                + " alerts."));

        if (items.existsByUserIdAndTermNorm(userId, normalised)) {
            throw new InvalidWatchException("You are already watching that.");
        }
        if (items.countByUserId(userId) >= MAXIMUM_WATCHES) {
            throw new InvalidWatchException("You can watch up to " + MAXIMUM_WATCHES + " medicines.");
        }

        // The baseline: alert months at or before this are not notified, so adding a watch does
        // not send an email for every month the archive already holds.
        String latestMonth = latestAlertMonth();
        WatchlistItemEntity saved =
                items.save(new WatchlistItemEntity(userId, typedTerm.trim(), normalised, latestMonth, clock.instant()));
        return toWatch(saved);
    }

    @Transactional(readOnly = true)
    public List<Watch> list(Long userId) {
        return items.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(WatchlistService::toWatch)
                .toList();
    }

    @Transactional
    public void remove(Long userId, Long watchId) {
        // Scoped by user as well as id: without that, anybody could delete anybody's watch by
        // guessing a number. The 404 is deliberate too - "not yours" and "does not exist" look
        // the same from outside.
        WatchlistItemEntity item =
                items.findByIdAndUserId(watchId, userId).orElseThrow(() -> new NotFoundException("No such watch"));
        items.delete(item);
    }

    /** The newest alert month the warehouse holds, used as a new watch's baseline. */
    private String latestAlertMonth() {
        return jdbc.sql("SELECT coalesce(max(alert_month), '0000-00') FROM gold.fact_nsq_sample")
                .query(String.class)
                .single();
    }

    private static Watch toWatch(WatchlistItemEntity item) {
        return new Watch(item.getId(), item.getTerm(), item.getSinceAlertMonth(), item.getCreatedAt());
    }

    /** One watch, as its owner sees it. */
    public record Watch(Long id, String term, String notifiedFromAfter, java.time.Instant createdAt) {}

    /** The term could not be used, or is already watched. */
    public static class InvalidWatchException extends RuntimeException {
        public InvalidWatchException(String message) {
            super(message);
        }
    }
}
