package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.batches.domain.BatchSearchResult;
import in.drugwatch.api.batches.domain.BatchSearchService;
import in.drugwatch.api.batches.domain.Finding;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.jdbc.Sql;

/**
 * The batch checker against a real Postgres holding an invented gold layer.
 *
 * <p>The fixture's rows are fictional by design (ADR 0003 keeps real CDSCO findings out of git),
 * but their shapes are the ones the archive actually contains: punctuated batch numbers, the "Not
 * applicable" sentinel, a batch that belongs to two different medicines, and a spurious finding
 * with no manufacturer.
 */
@SpringBootTest
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
class BatchSearchTest {

    @Autowired
    BatchSearchService search;

    @Test
    void a_flagged_batch_is_found_even_when_the_user_omits_the_punctuation() {
        // The archive stores "KA/018"; a user copying from a foil strip types "KA018".
        BatchSearchResult result = search.search("Zyntophil", "KA018");

        assertThat(result.outcome()).isEqualTo(BatchSearchResult.Outcome.FLAGGED);
        assertThat(result.findings()).extracting(Finding::batchNumber).contains("KA/018");
    }

    @Test
    void the_same_batch_written_three_ways_is_one_batch() {
        // "KA/018", "KA-018" and "KA 018" are all in the fixture, as they are in the archive.
        assertThat(search.search("Zyntophil", "KA/018").findings()).hasSize(2);
        assertThat(search.search("Zyntophil", "ka 018").findings()).hasSize(2);
        assertThat(search.search("Zyntophil", "Ka-018").findings()).hasSize(2);
    }

    @Test
    void every_finding_carries_what_a_reader_needs_to_check_it() {
        // CLAUDE.md §6: batch number, alert month, and a link to the original CDSCO document.
        BatchSearchResult result = search.search("Zyntophil", "KA018");

        assertThat(result.findings()).allSatisfy(finding -> {
            assertThat(finding.batchNumber()).isNotBlank();
            assertThat(finding.alertMonth()).matches("\\d{4}-\\d{2}");
            assertThat(finding.sourceUrl()).isNotBlank();
        });
    }

    @Test
    void a_clean_result_says_what_it_does_not_mean() {
        BatchSearchResult result = search.search("Zyntophil", "ZZ999");

        assertThat(result.outcome()).isEqualTo(BatchSearchResult.Outcome.NOT_FOUND);
        assertThat(result.findings()).isEmpty();
        // "Not found" never means "guaranteed safe".
        assertThat(result.meaning()).contains("not a guarantee of safety");
        assertThat(result.meaning()).contains("101 of the 111 months");
    }

    @Test
    void every_result_carries_the_disclaimer() {
        for (BatchSearchResult result : java.util.List.of(
                search.search("Zyntophil", "KA018"),
                search.search("Zyntophil", "ZZ999"),
                search.search("Zyntophil", "Not applicable"))) {
            assertThat(result.disclaimer()).isEqualTo("Not medical advice. Data from CDSCO public alerts.");
        }
    }

    // ------------------------------------------------------------------ the refusals

    @Test
    void the_not_applicable_sentinel_matches_nothing() {
        // It is the printed batch number on 22 real findings. Searching for it would report a
        // medicine as flagged on the strength of a missing value.
        BatchSearchResult result = search.search("Calmirex", "Not applicable");

        assertThat(result.outcome()).isEqualTo(BatchSearchResult.Outcome.NOT_SEARCHABLE);
        assertThat(result.findings()).isEmpty();
        assertThat(result.meaning()).contains("identify nothing");
    }

    @Test
    void a_batch_number_too_short_to_identify_anything_is_refused() {
        // "1" and "6" are real batch numbers on several findings from different manufacturers.
        assertThat(search.search("Zyntophil", "1").outcome()).isEqualTo(BatchSearchResult.Outcome.NOT_SEARCHABLE);
    }

    @Test
    void a_match_requires_the_medicine_as_well_as_the_batch() {
        // The batch KA/018 exists, but not on this medicine. Reporting it as flagged would be a
        // claim about the wrong product.
        BatchSearchResult result = search.search("Calmirex", "KA018");

        assertThat(result.outcome()).isEqualTo(BatchSearchResult.Outcome.NOT_FOUND);
        assertThat(result.findings()).isEmpty();
    }

    @Test
    void the_same_batch_on_another_medicine_is_shown_as_a_close_match() {
        // §4.1's "close matches": useful, and clearly not the same as a match. It is how a user
        // discovers they typed the medicine's name differently from the way CDSCO printed it.
        BatchSearchResult result = search.search("Calmirex", "KA018");

        assertThat(result.sameBatchOtherMedicines())
                .extracting(Finding::productName)
                .contains("Zyntophil Tablets IP 40 mg", "Brivolax Oral Suspension");
    }

    // ------------------------------------------------------------------ spurious findings

    @Test
    void a_spurious_finding_never_names_a_manufacturer() {
        // The company printed on a counterfeit pack is the brand somebody copied - the victim.
        BatchSearchResult result = search.search("Zyntophil", "SPU-77");

        assertThat(result.findings()).hasSize(1);
        Finding spurious = result.findings().getFirst();
        assertThat(spurious.spurious()).isTrue();
        assertThat(spurious.manufacturerName()).isNull();
        assertThat(spurious.manufacturerId()).isNull();
        assertThat(spurious.nameOnPack()).isEqualTo("Zyntophil");
    }

    @Test
    void a_spurious_result_explains_who_the_named_company_is() {
        BatchSearchResult result = search.search("Zyntophil", "SPU-77");

        assertThat(result.meaning()).contains("the brand that was copied");
        assertThat(result.meaning()).contains("did not make this pack");
    }

    @Test
    void an_ordinary_finding_does_name_its_manufacturer() {
        // The other half of the rule: suppressing the manufacturer everywhere would make the
        // archive useless. It is suppressed for spurious findings specifically.
        BatchSearchResult result = search.search("Zyntophil Tablets IP 40 mg", "KA018");

        assertThat(result.findings())
                .filteredOn(finding -> !finding.spurious())
                .allSatisfy(finding -> assertThat(finding.manufacturerName()).isNotBlank());
    }
}
