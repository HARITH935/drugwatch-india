package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.batches.domain.BatchNumber;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

/**
 * Batch-number normalisation: what it must merge, and what it must never merge.
 *
 * <p>Every case here comes from the real archive rather than from imagination - the punctuation
 * forms, the sentinel, and the short numeric batches all exist in CDSCO's published alerts.
 */
class BatchNumberTest {

    @ParameterizedTest
    @CsvSource({
        // 40% of the archive's batch numbers carry punctuation; a user copying from a strip does
        // not type it.
        "KA/018, KA018",
        "TETY-01, TETY01",
        "LZR-2204, LZR2204",
        "'ABC 123', ABC123",
        "a.b.c, ABC",
        // Case varies on the pack and in the alert.
        "tst2301, TST2301",
    })
    void punctuation_and_case_do_not_stop_a_match(String printed, String expected) {
        assertThat(BatchNumber.normalise(printed)).contains(expected);
    }

    @Test
    void a_leading_zero_is_part_of_the_batch_number() {
        // Both "01" and "1" are real batch numbers in the archive. Treating them as the same
        // would merge two different batches into one claim about somebody's medicine.
        assertThat(BatchNumber.normalise("01")).contains("01");
        assertThat(BatchNumber.normalise("1")).isEmpty(); // too short to search on at all
        assertThat(BatchNumber.normalise("001")).contains("001");
        assertThat(BatchNumber.normalise("01")).isNotEqualTo(BatchNumber.normalise("001"));
    }

    @Test
    void letters_are_never_transliterated_to_digits() {
        // O to 0 and I to 1 look like helpful corrections and turn one manufacturer's batch into
        // another's.
        assertThat(BatchNumber.normalise("BO1")).contains("BO1");
        assertThat(BatchNumber.normalise("B01")).contains("B01");
        assertThat(BatchNumber.normalise("BO1")).isNotEqualTo(BatchNumber.normalise("B01"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"Not applicable", "not applicable", "N/A", "NA", "nil", "unknown", "Not Available"})
    void a_sentinel_is_not_a_batch_number(String sentinel) {
        // "Not applicable" is the printed batch number on 22 findings. Without this, searching for
        // a medicine whose batch is genuinely unrecorded would report it as flagged.
        assertThat(BatchNumber.normalise(sentinel)).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "   ", "-", "/", "...", "6"})
    void something_that_is_not_a_batch_number_returns_empty(String input) {
        assertThat(BatchNumber.normalise(input)).isEmpty();
    }

    @Test
    void null_is_handled_rather_than_thrown() {
        assertThat(BatchNumber.normalise(null)).isEmpty();
    }

    @Test
    void empty_means_do_not_search_never_search_for_everything() {
        // The distinction that matters at the call site: an unsearchable batch must produce no
        // query, not a query with no filter.
        assertThat(BatchNumber.isSearchable("Not applicable")).isFalse();
        assertThat(BatchNumber.isSearchable("TETY-01")).isTrue();
    }
}
