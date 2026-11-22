package in.drugwatch.api.alerts.api;

import in.drugwatch.api.alerts.domain.AlertService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10: {@code GET /api/v1/alerts/latest}. */
@RestController
@Tag(name = "Alerts", description = "The most recent CDSCO alert month")
@RequestMapping("/api/v1/alerts")
public class AlertController {

    private final AlertService alerts;

    AlertController(AlertService alerts) {
        this.alerts = alerts;
    }

    @Operation(
            summary = "The latest alert month",
            description = "Which month the archive currently reaches, and that month's findings."
                    + " CDSCO publishes monthly, so this is also how fresh the whole site is.")
    @GetMapping("/latest")
    public AlertService.LatestAlerts latest() {
        return alerts.latest();
    }
}
