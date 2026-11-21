package in.drugwatch.api.alerts.api;

import in.drugwatch.api.alerts.domain.AlertService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Plan §10: {@code GET /api/v1/alerts/latest}. */
@RestController
@RequestMapping("/api/v1/alerts")
public class AlertController {

    private final AlertService alerts;

    AlertController(AlertService alerts) {
        this.alerts = alerts;
    }

    @GetMapping("/latest")
    public AlertService.LatestAlerts latest() {
        return alerts.latest();
    }
}
