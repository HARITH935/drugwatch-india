package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;

import in.drugwatch.api.watchlist.domain.WatchTerm;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

/** What may become a watch term, and what may not. */
class WatchTermTest {

    @ParameterizedTest
    @CsvSource({
        "Telmisartan, telmisartan",
        "'  Telmisartan  ', telmisartan",
        "'Vitamin   D3', vitamin d3",
        "Co-Trimoxazole, co-trimoxazole",
    })
    void a_term_is_lower_cased_with_whitespace_collapsed(String typed, String expected) {
        assertThat(WatchTerm.normalise(typed)).contains(expected);
    }

    @Test
    void hyphens_and_apostrophes_survive_because_they_are_part_of_medicine_names() {
        assertThat(WatchTerm.normalise("co-trimoxazole")).contains("co-trimoxazole");
        assertThat(WatchTerm.normalise("ringer's lactate")).contains("ringer's lactate");
    }

    @ParameterizedTest
    @ValueSource(strings = {"ab", "a", "", "   "})
    void something_too_short_to_identify_a_medicine_is_refused(String input) {
        // A one- or two-letter term matches most of the archive, so every month would bring an
        // email - which is indistinguishable from spam from the reader's side.
        assertThat(WatchTerm.normalise(input)).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {".*", "a|b", "para(cetamol", "a.b", "[abc]", "a+b", "^para", "100%"})
    void anything_that_means_something_to_a_regex_is_refused(String input) {
        // The term is interpolated into a word-boundary regex when matching, so a pattern here
        // would become a pattern there. Refused at the edge rather than escaped later - the same
        // rule the drug-class vocabulary applies to its ingredient phrases.
        assertThat(WatchTerm.normalise(input)).isEmpty();
    }

    @Test
    void a_term_longer_than_a_medicine_name_is_refused() {
        assertThat(WatchTerm.normalise("a".repeat(101))).isEmpty();
    }

    @Test
    void null_is_handled_rather_than_thrown() {
        assertThat(WatchTerm.normalise(null)).isEmpty();
    }
}
