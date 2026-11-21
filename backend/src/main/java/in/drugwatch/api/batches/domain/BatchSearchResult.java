package in.drugwatch.api.batches.domain;

import in.drugwatch.api.shared.PublicNotes;
import java.util.List;

/**
 * What a batch search found, with the words that must go with it.
 *
 * <p>The explanation is part of the result rather than something the caller is trusted to add.
 * CLAUDE.md §6's rules - "not found" is not a guarantee, a finding is about one batch - are
 * carried by the response itself, so a second client or somebody reading the JSON gets them too.
 */
public record BatchSearchResult(
        String drug,
        String batch,
        Outcome outcome,
        List<Finding> findings,
        List<Finding> sameBatchOtherMedicines,
        String meaning,
        String disclaimer) {

    public enum Outcome {
        /** At least one alert names this batch of this medicine. */
        FLAGGED,
        /** No alert names it. Not a statement about safety. */
        NOT_FOUND,
        /** The batch number given cannot be searched for - a sentinel, or too short. */
        NOT_SEARCHABLE
    }

    public static BatchSearchResult flagged(
            String drug, String batch, List<Finding> findings, List<Finding> otherMedicines) {
        boolean anySpurious = findings.stream().anyMatch(Finding::spurious);
        String meaning = anySpurious
                ? PublicNotes.FLAGGED_MEANING + " " + PublicNotes.SPURIOUS_MEANING
                : PublicNotes.FLAGGED_MEANING;
        return new BatchSearchResult(
                drug, batch, Outcome.FLAGGED, findings, otherMedicines, meaning, PublicNotes.DISCLAIMER);
    }

    public static BatchSearchResult notFound(String drug, String batch, List<Finding> otherMedicines) {
        return new BatchSearchResult(
                drug,
                batch,
                Outcome.NOT_FOUND,
                List.of(),
                otherMedicines,
                PublicNotes.NOT_FOUND_MEANING,
                PublicNotes.DISCLAIMER);
    }

    public static BatchSearchResult notSearchable(String drug, String batch) {
        return new BatchSearchResult(
                drug,
                batch,
                Outcome.NOT_SEARCHABLE,
                List.of(),
                List.of(),
                "That batch number cannot be searched for. Batch numbers like \"Not applicable\" or a"
                        + " single character appear in the alerts but identify nothing, so searching"
                        + " for them would return findings that are not about your medicine.",
                PublicNotes.DISCLAIMER);
    }
}
