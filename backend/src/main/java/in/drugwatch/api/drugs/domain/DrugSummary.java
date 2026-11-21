package in.drugwatch.api.drugs.domain;

import java.util.List;

/** A medicine as CDSCO printed its name, with how often it has been reported. */
public record DrugSummary(
        String drugId,
        String productName,
        String genericName,
        String dosageForm,
        List<String> strengths,
        List<String> drugClasses,
        long findings,
        String firstAlertMonth,
        String lastAlertMonth) {}
