package in.drugwatch.api.batches.domain;

import java.util.List;

/**
 * One reported finding, in the shape the public may see it.
 *
 * <p>Three fields are mandatory by CLAUDE.md §6 and are therefore not nullable here: the batch
 * number, the alert month, and the link to the original CDSCO document. A reader must always be
 * able to check the claim at its source.
 *
 * <p>{@code manufacturerName} is null for a spurious finding, and that is structural rather than
 * careful coding: {@code gold.fact_nsq_sample} carries no {@code manufacturer_id} for those rows
 * at all (Phase 4), so there is nothing to join to. The copied brand is in {@code nameOnPack}.
 */
public record Finding(
        String batchNumber,
        String alertMonth,
        String productName,
        String failureReason,
        List<String> failureCategories,
        boolean spurious,
        String nameOnPack,
        String manufacturerId,
        String manufacturerName,
        String reportedBy,
        String labType,
        String sourceUrl) {

    public Finding {
        if (batchNumber == null || alertMonth == null || sourceUrl == null) {
            throw new IllegalArgumentException(
                    "a published finding must always carry its batch number, alert month and source document");
        }
        if (spurious && manufacturerName != null) {
            // The rule the whole spurious design protects: the name on a counterfeit pack is the
            // victim. Attributing it to that company would be an accusation the data does not make.
            throw new IllegalArgumentException("a spurious finding must not name a manufacturer");
        }
        failureCategories = failureCategories == null ? List.of() : List.copyOf(failureCategories);
    }
}
