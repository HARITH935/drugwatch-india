package in.drugwatch.api.manufacturers.api;

import in.drugwatch.api.manufacturers.domain.ManufacturerService;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10: {@code GET /api/v1/manufacturers/{id}}. */
@RestController
@RequestMapping("/api/v1/manufacturers")
@Validated
public class ManufacturerController {

    private final ManufacturerService manufacturers;

    ManufacturerController(ManufacturerService manufacturers) {
        this.manufacturers = manufacturers;
    }

    @GetMapping("/{id}")
    public ManufacturerService.ManufacturerPage page(@PathVariable @NotBlank @Size(max = 64) String id) {
        return manufacturers.page(id);
    }
}
