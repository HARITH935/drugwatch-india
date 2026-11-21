package in.drugwatch.api.shared;

/**
 * The sentences that must travel with CDSCO data wherever it is shown (CLAUDE.md §6).
 *
 * <p>They live in the API's responses rather than in the website's templates on purpose: a
 * redesign of the frontend, a second client, or somebody reading the JSON directly must all get
 * the caveat. A disclaimer that only exists in a page template is a disclaimer one refactor away
 * from disappearing.
 */
public final class PublicNotes {

    /** Required on every page that shows this data. */
    public static final String DISCLAIMER = "Not medical advice. Data from CDSCO public alerts.";

    /**
     * What a clean result means, and what it does not. CLAUDE.md §6: "Not found" never means
     * "guaranteed safe". 101 of the 111 months the archive spans were published at all, sampling
     * is not random, and a batch nobody tested cannot appear.
     */
    public static final String NOT_FOUND_MEANING =
            "This batch does not appear in the CDSCO alerts we hold. That is not a guarantee of"
                    + " safety: only sampled batches are tested, sampling is not random, and CDSCO"
                    + " published alerts for 101 of the 111 months this archive spans.";

    /** What a match means, and the limit of it. One batch, not a product and not a company. */
    public static final String FLAGGED_MEANING =
            "This finding applies to one specific batch that a laboratory tested. It is not a"
                    + " statement about the product in general or about the company.";

    /**
     * Shown with a spurious finding. The company named on a counterfeit pack is the brand somebody
     * copied - the victim of the counterfeit, not its maker (CLAUDE.md §6).
     */
    public static final String SPURIOUS_MEANING =
            "This pack was reported as spurious (counterfeit). The name printed on it is the brand"
                    + " that was copied; the company of that name did not make this pack.";

    private PublicNotes() {}
}
