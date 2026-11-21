package in.drugwatch.api;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.classes;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

/**
 * The layering, enforced as a test (ADR 0018).
 *
 * <p>The plan asks for controller to service to repository. Written down, that lasts until the
 * first afternoon when calling the repository from the controller is two lines shorter. These
 * rules are the same instinct as the dbt test that refuses a drug class nobody reviewed, or the
 * test that reads docker-compose.yml to check the risk service holds no database credentials: a
 * rule with nothing checking it is a comment.
 */
@AnalyzeClasses(
        packages = "in.drugwatch.api",
        importOptions = {ImportOption.DoNotIncludeTests.class})
class ArchitectureTest {

    /**
     * The rule that matters. A controller reaching past the service layer is how request handling
     * and business logic end up in the same method, and how the same lookup gets written twice.
     */
    @ArchTest
    static final ArchRule controllers_do_not_touch_repositories = noClasses()
            .that()
            .haveSimpleNameEndingWith("Controller")
            .should()
            .dependOnClassesThat()
            .haveSimpleNameEndingWith("Repository")
            .because("a controller handles HTTP and delegates; the service layer owns the data access");

    /** Data access must not know what an HTTP request is. */
    @ArchTest
    static final ArchRule repositories_do_not_depend_on_the_layers_above = noClasses()
            .that()
            .haveSimpleNameEndingWith("Repository")
            .should()
            .dependOnClassesThat()
            .haveSimpleNameEndingWith("Controller")
            .orShould()
            .dependOnClassesThat()
            .haveSimpleNameEndingWith("Service")
            .because("a repository is the bottom layer: it is used by the layers above, and uses none of them");

    /**
     * Controllers are the HTTP surface, so they live where someone looking for the API can find
     * them - beside the feature they serve, never in a shared bucket.
     */
    @ArchTest
    static final ArchRule controllers_live_in_their_feature_package = classes()
            .that()
            .haveSimpleNameEndingWith("Controller")
            .should()
            .resideOutsideOfPackage("in.drugwatch.api")
            .because("code is organised by feature; a controller belongs to one");

    /**
     * The layering rules above have something to check.
     *
     * <p>ArchUnit normally fails a rule that matched no classes, and {@code archunit.properties}
     * turns that off because the step-0 skeleton had no controllers. This is what makes that
     * allowance safe: if every controller were renamed, the rules would silently stop applying
     * and this would fail instead.
     */
    @ArchTest
    static final ArchRule the_api_has_controllers_to_check = classes()
            .that()
            .haveSimpleNameEndingWith("Controller")
            .should()
            .beAnnotatedWith(org.springframework.web.bind.annotation.RestController.class)
            .allowEmptyShould(false)
            .because("if this matches nothing, the layering rules are checking nothing either");

    /**
     * Exactly one class may sit in the root package: the application entry point. Everything else
     * belongs to a feature, and a class that drifts to the root is how a "shared" bucket starts.
     *
     * <p>This rule also exists to have something to check while the skeleton has no controllers -
     * see src/test/resources/archunit.properties.
     */
    @ArchTest
    static final ArchRule only_the_entry_point_lives_in_the_root_package = classes()
            .that()
            .resideInAPackage("in.drugwatch.api")
            .should()
            .haveSimpleName("DrugWatchApiApplication")
            .because("every other class belongs to a feature package");
}
