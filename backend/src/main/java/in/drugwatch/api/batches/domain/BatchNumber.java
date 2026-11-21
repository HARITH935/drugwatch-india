package in.drugwatch.api.batches.domain;

import java.util.Locale;
import java.util.Optional;

/**
 * Normalising a batch number so that what a person reads off a strip matches what CDSCO printed.
 *
 * <p>Measured on the archive (2026-11-21, 7,126 findings): <b>2,841 batch numbers - 40% - contain
 * a space, a hyphen, a slash or a dot</b>. {@code KA/018}, {@code TETY-01}, {@code LZR-2204}. A
 * user copying from a foil strip types {@code KA018}, and an exact comparison finds nothing.
 *
 * <p>So both sides are reduced to letters and digits, upper-cased. What that does <b>not</b> do is
 * as important:
 *
 * <ul>
 *   <li><b>Leading zeros are kept.</b> {@code 01} and {@code 1} are different batch numbers and
 *       both exist in the archive. Dropping them would merge two real batches into one claim.
 *   <li><b>Letters are never dropped or transliterated.</b> No {@code O} to {@code 0}, no {@code I}
 *       to {@code 1}. Those substitutions look helpful and turn one manufacturer's batch into
 *       another's.
 * </ul>
 *
 * <p>Checked against the data: normalising this way takes 6,807 distinct printed batch numbers to
 * 6,766 - it merges 41 spellings, not thousands. CLAUDE.md §5's "a missed merge is better than a
 * wrong merge" is a rule about manufacturers, and it applies here for the same reason: a wrong
 * match tells somebody their medicine was flagged when it was not.
 */
public final class BatchNumber {

    /**
     * Values that are not batch numbers at all. {@code "Not applicable"} is printed as the batch
     * number on <b>22 findings</b>, so without this a user searching for a medicine whose batch is
     * genuinely unknown would be told it was flagged.
     */
    private static final java.util.Set<String> SENTINELS =
            java.util.Set.of("NOTAPPLICABLE", "NA", "NIL", "NOTAVAILABLE", "NOTMENTIONED", "UNKNOWN");

    /** Shorter than this and a "batch number" is not one; it would match a large part of the archive. */
    private static final int MINIMUM_LENGTH = 2;

    private BatchNumber() {}

    /**
     * The comparable form of a batch number, or empty when the input cannot be one.
     *
     * <p>Empty means "do not search for this", never "search for everything".
     */
    public static Optional<String> normalise(String printed) {
        if (printed == null) {
            return Optional.empty();
        }
        StringBuilder kept = new StringBuilder(printed.length());
        for (char character : printed.toCharArray()) {
            if (Character.isLetterOrDigit(character)) {
                kept.append(character);
            }
        }
        String normalised = kept.toString().toUpperCase(Locale.ROOT);

        if (normalised.length() < MINIMUM_LENGTH || SENTINELS.contains(normalised)) {
            return Optional.empty();
        }
        return Optional.of(normalised);
    }

    /** Whether a stored batch number is one a search may ever match. */
    public static boolean isSearchable(String stored) {
        return normalise(stored).isPresent();
    }
}
