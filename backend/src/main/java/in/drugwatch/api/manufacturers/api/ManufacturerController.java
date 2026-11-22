package in.drugwatch.api.manufacturers.api;

import in.drugwatch.api.manufacturers.domain.ManufacturerService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10: {@code GET /api/v1/manufacturers/{id}}. */
@RestController
@Tag(name = "Manufacturers", description = "One manufacturer's reported findings")
@RequestMapping("/api/v1/manufacturers")
@Validated
public class ManufacturerController {

    private final ManufacturerService manufacturers;

    ManufacturerController(ManufacturerService manufacturers) {
        this.manufacturers = manufacturers;
    }

    @Operation(
            summary = "One manufacturer's reporting history",
            description = "The findings reported against this manufacturer, by month and by product."
                    + " Spurious reports are excluded: the company named on a counterfeit pack is the"
                    + " brand that was copied, not the maker of that pack.")
    @GetMapping("/{id}")
    public ManufacturerService.ManufacturerPage page(@PathVariable @NotBlank @Size(max = 64) String id) {
        return manufacturers.page(id);
    }
}
