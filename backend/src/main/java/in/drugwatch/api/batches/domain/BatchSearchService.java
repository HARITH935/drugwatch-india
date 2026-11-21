package in.drugwatch.api.batches.domain;

import java.util.List;
import org.springframework.stereotype.Service;

/**
 * The batch checker (plan §4.1): "is my medicine batch flagged?"
 *
 * <p><b>Both a medicine and a batch are required.</b> The archive contains batch numbers like
 * {@code 1}, {@code 6} and {@code 01}, each on several findings from different manufacturers, so a
 * batch-only search would tell somebody their medicine was flagged on the strength of a one-digit
 * coincidence. Requiring the medicine name is what makes a match mean something.
 */
@Service
public class BatchSearchService {

    private final FindingRepository findings;

    BatchSearchService(FindingRepository findings) {
        this.findings = findings;
    }

    public BatchSearchResult search(String drug, String batch) {
        return BatchNumber.normalise(batch)
                .map(normalised -> searchFor(drug, batch, normalised))
                .orElseGet(() -> BatchSearchResult.notSearchable(drug, batch));
    }

    private BatchSearchResult searchFor(String drug, String batch, String normalisedBatch) {
        String drugText = drug.trim();
        List<Finding> matches = findings.findByBatchAndDrug(normalisedBatch, drugText);

        // Shown either way: if the batch exists on a different medicine, that is worth seeing
        // whether or not the named medicine matched - it is how a user discovers they typed the
        // medicine's name differently from the way CDSCO printed it.
        List<Finding> otherMedicines = findings.findByBatchOnly(normalisedBatch, drugText);

        return matches.isEmpty()
                ? BatchSearchResult.notFound(drug, batch, otherMedicines)
                : BatchSearchResult.flagged(drug, batch, matches, otherMedicines);
    }
}
