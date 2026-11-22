package in.drugwatch.api.watchlist.domain;

import java.util.Locale;
import java.util.Optional;

/**
 * Normalising what somebody types into something that can be matched against a product name.
 *
 * <p>A watch is a <b>term</b>, not one exact product (Phase 9 decision D). Phase 4 measured that
 * the archive prints the same medicine many ways - "Paracetamol Tablets IP 500 mg" and
 * "Paracetamol Tab. 500mg" are two rows of {@code dim_drug} - and deliberately did not merge them,
 * because deciding two printed names are one product needs reviewed evidence. A watch pinned to
 * one of those rows would silently miss the other, and for somebody watching their own medicine a
 * missed alert is worse than an extra email.
 *
 * <p>Matching is on <b>whole words</b>, for the same reason the drug-class vocabulary is: a
 * substring match would make "ace" match "Paracetamol", and every month would bring an email.
 */
public final class WatchTerm {

    /** Shorter than this matches most of the archive; longer is not a medicine name. */
    private static final int MINIMUM = 3;

    private static final int MAXIMUM = 100;

    private WatchTerm() {}

    /**
     * The comparable form, or empty when the input cannot be a watch term.
     *
     * <p>Collapses whitespace and lower-cases. Punctuation is kept rather than stripped, because
     * it carries meaning in a medicine name - "Vitamin D3" and "co-trimoxazole" are words - but
     * the characters a regex would treat as syntax are refused outright, so a term can never
     * become a pattern.
     */
    public static Optional<String> normalise(String typed) {
        if (typed == null) {
            return Optional.empty();
        }
        String collapsed = typed.trim().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
        if (collapsed.length() < MINIMUM || collapsed.length() > MAXIMUM) {
            return Optional.empty();
        }
        // Letters, digits, spaces, hyphens and apostrophes only. The term is interpolated into a
        // word-boundary regex when matching, so anything that means something to a regex engine
        // is refused here rather than escaped later - the same rule the drug-class vocabulary
        // applies to its ingredient phrases.
        if (!collapsed.matches("[a-z0-9][a-z0-9 '\\-]*")) {
            return Optional.empty();
        }
        return Optional.of(collapsed);
    }
}
