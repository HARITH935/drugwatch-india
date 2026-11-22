package in.drugwatch.api.drugs.domain;

import in.drugwatch.api.batches.domain.Finding;
import in.drugwatch.api.config.CacheConfig;
import in.drugwatch.api.shared.NotFoundException;
import in.drugwatch.api.shared.PublicNotes;
import java.util.List;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

/** Drug pages and search (plan §10). */
@Service
public class DrugService {

    private final DrugRepository drugs;

    DrugService(DrugRepository drugs) {
        this.drugs = drugs;
    }

    @Cacheable(cacheNames = CacheConfig.DRUG_PAGES, keyGenerator = "dataVersionKeyGenerator")
    public DrugPage page(String drugId) {
        DrugSummary drug = drugs.findById(drugId).orElseThrow(() -> new NotFoundException("No such medicine"));
        return new DrugPage(drug, drugs.findingsFor(drugId), PublicNotes.FLAGGED_MEANING, PublicNotes.DISCLAIMER);
    }

    @Cacheable(cacheNames = CacheConfig.DRUG_SEARCHES, keyGenerator = "dataVersionKeyGenerator")
    public DrugSearchResult search(String text, int limit) {
        List<DrugSummary> matches = drugs.search(text.trim(), limit);
        return new DrugSearchResult(text, matches, SEARCH_NOTE, PublicNotes.DISCLAIMER);
    }

    /**
     * Said on every search result. Phase 4 deliberately did not merge differently-printed names,
     * so a reader must know that two rows can be the same medicine - otherwise they will read
     * "two products" where the archive only has two spellings.
     */
    private static final String SEARCH_NOTE =
            "Medicines are listed as CDSCO printed them, so the same medicine can appear more than"
                    + " once under different spellings. They are not merged, because deciding two"
                    + " printed names are one product needs evidence we do not have.";

    /** A medicine's page: what it is, and every batch of it that has been reported. */
    public record DrugPage(DrugSummary drug, List<Finding> findings, String meaning, String disclaimer) {}

    /** Search results, with the note about unmerged spellings. */
    public record DrugSearchResult(String query, List<DrugSummary> matches, String note, String disclaimer) {}
}
