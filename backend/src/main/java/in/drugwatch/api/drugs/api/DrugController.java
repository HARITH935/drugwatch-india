package in.drugwatch.api.drugs.api;

import in.drugwatch.api.drugs.domain.DrugService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10: {@code GET /api/v1/drugs/{id}} and {@code GET /api/v1/drugs/search}. */
@RestController
@Tag(name = "Drugs", description = "One medicine: its alert history, and the search that finds it")
@RequestMapping("/api/v1/drugs")
@Validated
public class DrugController {

    private final DrugService drugs;

    DrugController(DrugService drugs) {
        this.drugs = drugs;
    }

    @Operation(
            summary = "One medicine's alert history",
            description = "Every finding reported against this product name, newest alert month first,"
                    + " each with its batch number and a link to the CDSCO document it came from.")
    @GetMapping("/{id}")
    public DrugService.DrugPage page(@PathVariable @NotBlank @Size(max = 64) String id) {
        return drugs.page(id);
    }

    @Operation(
            summary = "Find a medicine by name",
            description = "Trigram search, so a near miss or a different spelling still finds the"
                    + " product. Ranked by similarity; it does not rank by how many findings a"
                    + " product has.")
    @GetMapping("/search")
    public DrugService.DrugSearchResult search(
            // Three characters minimum: shorter matches most of the archive and the result is a
            // list of everything, which is slower and tells the reader nothing.
            @RequestParam @NotBlank @Size(min = 3, max = 120) String q,
            @RequestParam(defaultValue = "20") @Min(1) @Max(50) int limit) {
        return drugs.search(q, limit);
    }
}
