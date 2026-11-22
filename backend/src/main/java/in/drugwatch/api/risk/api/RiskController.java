package in.drugwatch.api.risk.api;

import in.drugwatch.api.risk.domain.RiskService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Plan §10: {@code GET /api/v1/manufacturers/{id}/risk}.
 *
 * <p>The path belongs to the manufacturer resource; the code belongs to the risk feature, which is
 * why this controller sits in {@code risk} rather than {@code manufacturers}. A URL describes
 * where something is; a package describes what changes together.
 *
 * <p>Always 200 when the company exists, even when the model service is down - the answer "no
 * score right now" is a valid answer to "what is the score", and a 503 here would make a client
 * treat a working page as a broken one.
 */
@RestController
@Tag(name = "Risk score", description = "A model score describing reporting history, not product quality")
@RequestMapping("/api/v1/manufacturers")
@Validated
public class RiskController {

    private final RiskService risk;

    RiskController(RiskService risk) {
        this.risk = risk;
    }

    @Operation(
            summary = "The risk score for one manufacturer",
            description = "What the model makes of this manufacturer's reporting history, with the"
                    + " features that moved the score. It is not a prediction about any particular"
                    + " medicine, and a manufacturer the model never saw is returned as not scoreable"
                    + " rather than given a guess. Returns 503 while the scoring service is down.")
    @GetMapping("/{id}/risk")
    public RiskService.RiskResult risk(@PathVariable @NotBlank @Size(max = 64) String id) {
        return risk.scoreFor(id);
    }
}
