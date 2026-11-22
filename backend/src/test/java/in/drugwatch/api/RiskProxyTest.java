package in.drugwatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import in.drugwatch.api.risk.domain.RiskService;
import in.drugwatch.api.shared.NotFoundException;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.jdbc.Sql;

/**
 * The risk proxy with the model service unreachable.
 *
 * <p>That is the default in tests ({@code application.properties} points at a dead port), because
 * it is the path most worth exercising: a public page must survive the model being down, and the
 * failure must not read as "this company is safe".
 */
@SpringBootTest
@Import(TestDatabase.class)
@Sql("classpath:db/gold-fixture.sql")
class RiskProxyTest {

    @Autowired
    RiskService risk;

    @Test
    void the_page_still_answers_when_the_model_service_is_down() {
        var result = risk.scoreFor("m1");

        assertThat(result.available()).isFalse();
        assertThat(result.score()).isNull();
        assertThat(result.meaning()).contains("temporarily unavailable");
        // The important half: the rest of the page is CDSCO data and is unaffected.
        assertThat(result.meaning()).contains("unaffected");
    }

    @Test
    void an_unavailable_score_is_never_reported_as_a_low_score() {
        // A zero here would read as "this company is safe", which is the opposite of "we do not
        // know". Null is the only honest value.
        var result = risk.scoreFor("m1");

        assertThat(result.score()).isNull();
        assertThat(result.available()).isFalse();
    }

    @Test
    void the_company_name_and_feature_month_are_still_returned() {
        // Enough for the page to say what it was trying to score and how current the inputs were.
        var result = risk.scoreFor("m1");

        assertThat(result.name()).isEqualTo("Marvex Laboratories Private Limited");
        assertThat(result.featuresAsOfMonth()).isEqualTo("2026-03");
    }

    @Test
    void a_company_with_no_history_is_not_scoreable_and_says_why() {
        // Not an error and not a zero: the model has nothing to work from, and saying so is the
        // only answer that is not misleading.
        var result = risk.scoreFor("m2-no-features");

        assertThat(result.available()).isFalse();
        assertThat(result.meaning()).contains("no reported findings");
        assertThat(result.meaning()).contains("not a statement about its medicines");
    }

    @Test
    void an_unknown_company_is_a_404() {
        assertThatThrownBy(() -> risk.scoreFor("nope")).isInstanceOf(NotFoundException.class);
    }

    @Test
    void every_answer_carries_the_disclaimer() {
        for (String id : java.util.List.of("m1", "m2", "m2-no-features")) {
            assertThat(risk.scoreFor(id).disclaimer()).contains("Not medical advice");
        }
    }
}
