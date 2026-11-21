package in.drugwatch.api.drugs.api;

import in.drugwatch.api.drugs.domain.DrugService;
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
@RequestMapping("/api/v1/drugs")
@Validated
public class DrugController {

    private final DrugService drugs;

    DrugController(DrugService drugs) {
        this.drugs = drugs;
    }

    @GetMapping("/{id}")
    public DrugService.DrugPage page(@PathVariable @NotBlank @Size(max = 64) String id) {
        return drugs.page(id);
    }

    @GetMapping("/search")
    public DrugService.DrugSearchResult search(
            // Three characters minimum: shorter matches most of the archive and the result is a
            // list of everything, which is slower and tells the reader nothing.
            @RequestParam @NotBlank @Size(min = 3, max = 120) String q,
            @RequestParam(defaultValue = "20") @Min(1) @Max(50) int limit) {
        return drugs.search(q, limit);
    }
}
