package in.drugwatch.api.batches.api;

import in.drugwatch.api.batches.domain.BatchSearchResult;
import in.drugwatch.api.batches.domain.BatchSearchService;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** The batch checker: plan §10's {@code GET /api/v1/batches/search}. */
@RestController
@RequestMapping("/api/v1/batches")
@Validated
public class BatchController {

    private final BatchSearchService search;

    BatchController(BatchSearchService search) {
        this.search = search;
    }

    /**
     * Both parameters are required, and the medicine name has a minimum length.
     *
     * <p>A two-character medicine name would match most of the archive, and combined with a short
     * batch number would produce a confident-looking match built on a coincidence. The validation
     * is the feature, not a formality.
     */
    @GetMapping("/search")
    public BatchSearchResult search(
            @RequestParam @NotBlank @Size(min = 3, max = 120) String drug,
            @RequestParam @NotBlank @Size(min = 1, max = 60) String batch) {
        return search.search(drug, batch);
    }
}
