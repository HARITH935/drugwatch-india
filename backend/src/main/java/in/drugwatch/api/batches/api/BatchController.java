package in.drugwatch.api.batches.api;

import in.drugwatch.api.batches.domain.BatchSearchResult;
import in.drugwatch.api.batches.domain.BatchSearchService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** The batch checker: plan §10's {@code GET /api/v1/batches/search}. */
@RestController
@Tag(name = "Batch checker", description = "Is this specific batch in a CDSCO alert?")
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
    @Operation(
            summary = "Look up one batch of one medicine",
            description = "Matches the batch number ignoring case, spaces and punctuation, because the"
                    + " number printed on a strip and the number typed into a CDSCO alert are rarely"
                    + " punctuated the same way. A result either way carries what it means: a finding"
                    + " applies to that batch alone, and no finding is not a clean bill of health.")
    @GetMapping("/search")
    public BatchSearchResult search(
            @RequestParam @NotBlank @Size(min = 3, max = 120) String drug,
            @RequestParam @NotBlank @Size(min = 1, max = 60) String batch) {
        return search.search(drug, batch);
    }
}
