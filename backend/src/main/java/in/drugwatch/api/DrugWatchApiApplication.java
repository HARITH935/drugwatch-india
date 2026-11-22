package in.drugwatch.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Entry point for the DrugWatch India API (Phase 9).
 *
 * <p>The packages beneath this one are organised by <b>feature</b> - {@code batches}, {@code
 * drugs}, {@code manufacturers}, {@code auth}, {@code watchlist} - with the plan's layering
 * (controller to service to repository) applied <i>inside</i> each one. A top-level split into
 * {@code controllers}, {@code services} and {@code repositories} would put the three files that
 * change together in three different places, and would make "which code belongs to the batch
 * checker" a question nobody can answer by looking.
 *
 * <p>{@code ArchitectureTest} enforces the layering so it cannot decay quietly (ADR 0018).
 */
@SpringBootApplication
// The watchlist notifier runs on a daily cron (Phase 9 decision D: the API polls rather than
// Airflow calling in). Without this the schedule is parsed and never fires.
@EnableScheduling
// Binds the @ConfigurationProperties records (currently Superset's embedding settings).
@ConfigurationPropertiesScan
public class DrugWatchApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(DrugWatchApiApplication.class, args);
    }
}
