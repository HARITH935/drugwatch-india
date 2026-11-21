package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.alerts.domain.AlertService;
import in.drugwatch.api.drugs.domain.DrugService;
import in.drugwatch.api.manufacturers.domain.ManufacturerService;
import in.drugwatch.api.shared.NotFoundException;
import org.assertj.core.api.Assertions;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.jdbc.Sql;

/** The drug, manufacturer and alert endpoints, against the invented gold fixture. */
@SpringBootTest
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
class PublicEndpointsTest {

    @Autowired
    DrugService drugs;

    @Autowired
    ManufacturerService manufacturers;

    @Autowired
    AlertService alerts;

    // ------------------------------------------------------------------ drugs

    @Test
    void a_drug_page_lists_every_reported_batch_with_its_source() {
        var page = drugs.page("d1");

        assertThat(page.drug().productName()).isEqualTo("Zyntophil Tablets IP 40 mg");
        assertThat(page.findings()).isNotEmpty();
        assertThat(page.findings())
                .allSatisfy(finding -> assertThat(finding.sourceUrl()).isNotBlank());
        assertThat(page.disclaimer()).contains("Not medical advice");
    }

    @Test
    void a_drug_page_says_a_finding_is_about_one_batch() {
        assertThat(drugs.page("d1").meaning()).contains("one specific batch");
    }

    @Test
    void an_unknown_drug_is_a_not_found_rather_than_an_empty_page() {
        Assertions.assertThatThrownBy(() -> drugs.page("nope")).isInstanceOf(NotFoundException.class);
    }

    @Test
    void search_finds_a_medicine_by_part_of_its_name() {
        var result = drugs.search("Zyntophil", 20);

        assertThat(result.matches()).extracting(d -> d.productName()).contains("Zyntophil Tablets IP 40 mg");
    }

    @Test
    void search_survives_a_typo() {
        // pg_trgm's reason for being here (decision B): a user misremembering a long medicine
        // name should still find it.
        var result = drugs.search("Zynthophil", 20);

        assertThat(result.matches()).isNotEmpty();
    }

    @Test
    void search_warns_that_the_same_medicine_can_appear_twice() {
        // Phase 4 deliberately did not merge differently-printed names. A reader seeing two rows
        // must know they may be one medicine, or they will read it as two products.
        var result = drugs.search("Zyntophil", 20);

        assertThat(result.matches()).hasSizeGreaterThan(1); // "Tablets IP 40 mg" and "Tab. 40mg"
        assertThat(result.note()).contains("the same medicine can appear more than once");
        assertThat(result.note()).contains("not merged");
    }

    // ------------------------------------------------------------------ manufacturers

    @Test
    void a_manufacturer_page_counts_reported_batches_and_says_what_that_means() {
        var page = manufacturers.page("m1");

        assertThat(page.manufacturer().name()).isEqualTo("Marvex Laboratories Private Limited");
        assertThat(page.manufacturer().reportedBatches()).isPositive();
        assertThat(page.meaning()).contains("reporting history rather than of quality");
        assertThat(page.meaning()).contains("Sampling is not random");
    }

    @Test
    void a_manufacturer_page_gives_the_span_beside_the_count() {
        // 12 findings over 8 years and 12 in one month read very differently; a bare count hides
        // the difference.
        var page = manufacturers.page("m1");

        assertThat(page.manufacturer().alertMonths()).isPositive();
        assertThat(page.manufacturer().firstAlertMonth()).isNotBlank();
        assertThat(page.manufacturer().lastAlertMonth()).isNotBlank();
    }

    @Test
    void a_spurious_finding_never_reaches_a_manufacturer_page() {
        // The fixture's spurious row names "Zyntophil" on the pack, and Zyntophil is made by m1.
        // It must not be counted against m1 - and it is not, because the row carries no
        // manufacturer_id at all, so there is nothing to join.
        var page = manufacturers.page("m1");

        assertThat(page.medicines()).extracting(m -> m.productName()).doesNotContain("SPU-77");
        // m1's real findings: KA/018 on d1, "Not applicable" on d4, KA 018 on d2 = 3.
        assertThat(page.manufacturer().reportedBatches()).isEqualTo(3);
    }

    @Test
    void an_unknown_manufacturer_is_a_not_found() {
        Assertions.assertThatThrownBy(() -> manufacturers.page("nope")).isInstanceOf(NotFoundException.class);
    }

    // ------------------------------------------------------------------ alerts

    @Test
    void the_latest_alert_month_is_the_newest_one_in_the_archive() {
        var latest = alerts.latest();

        assertThat(latest.alertMonth()).isEqualTo("2026-03");
        assertThat(latest.findings()).isEqualTo(1);
    }

    @Test
    void the_finding_count_is_shown_beside_the_number_of_reporting_laboratories() {
        // Phase 6 measured these at r = 0.964 across years. Publishing the first without the
        // second invites "quality is getting worse", which the archive does not support.
        var latest = alerts.latest();

        assertThat(latest.reportingLabs()).isPositive();
        assertThat(latest.note()).contains("more testing, not worse medicine");
    }
}
