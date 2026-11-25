export const metadata = {
  title: "About & Methodology - DrugWatch India",
  description:
    "Where this site's data comes from, how it's built, and what a result does and doesn't mean.",
};

export default function AboutPage() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-10 px-4 py-10">
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">About &amp; Methodology</h1>
        <p>
          DrugWatch India makes India&apos;s CDSCO &ldquo;Not of Standard Quality&rdquo; (NSQ) and
          spurious-drug alerts searchable, with a batch checker, manufacturer reporting history, and
          a few charts. Everything here is built from those public alerts - nothing is independently
          tested or verified by this site.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Where the data comes from</h2>
        <p>
          India&apos;s drug regulator (CDSCO) publishes two kinds of alert: central- and
          state-laboratory NSQ findings, and spurious (counterfeit) drug findings. Until August 2025
          these were monthly PDF files; since then, CDSCO has published them through a web portal as
          structured data. This site uses both - the portal&apos;s data back to January 2019, and
          the older PDF archive for the months the portal doesn&apos;t cover.
        </p>
        <p>
          As last measured (19 November 2026), the combined archive holds{" "}
          <strong>7,126 findings across 101 published alert months</strong>, from January 2019 to
          September 2026, plus a thin tail of PDF-only findings from 2017-2018.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">How a PDF becomes a row</h2>
        <p>
          Most of the archive now arrives already structured, from the portal. The remaining PDF
          files are parsed automatically: each one is matched to a table layout first - CDSCO has
          used at least six different header styles over the years - then read with that
          layout&apos;s own rules, rather than guessed row by row. A file that doesn&apos;t match a
          known layout is reported, not silently skipped.
        </p>
        <p>
          An earlier version of this pipeline tried a fine-tuned language model as a fallback, for
          the rows the automatic parser was least confident about. Measured honestly against a set
          of rows a person had labelled by hand - read once, for this measurement, and never used to
          train anything - the model&apos;s corrections scored worse than the parser&apos;s own
          output on both of two tests agreed before the measurement was taken, and a manual check
          against the real archive found it had corrupted a small number of genuine batch numbers.{" "}
          <strong>That fallback was built, measured, and not shipped</strong> - every row on this
          site comes from the plain rule-based parser or the portal directly, never from a model.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">
          The rising numbers are testing effort, not falling quality
        </h2>
        <p>
          The number of findings in this archive rose roughly five-fold between 2019 and 2025. Over
          the same years, the number of distinct laboratories named in those alerts rose nearly
          seven-fold, and the two series move together closely (correlation 0.964 across years).
          More findings mostly means more testing, not more failures - which is why this site never
          shows a bare &ldquo;findings per year&rdquo; count as if it meant quality was falling.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">The manufacturer risk score</h2>
        <p>
          A manufacturer&apos;s page can show a score: roughly, how likely that company is to appear
          in a new NSQ alert in the next six months, based only on its own reporting history so far.
        </p>
        <p>
          <strong>It does not predict whether a company&apos;s medicines are safe</strong>, or
          whether it will do anything wrong. CDSCO&apos;s testing isn&apos;t random - a company
          tested often has more chances to appear, and a company never sampled can&apos;t appear at
          all - so the score reflects reporting history and testing attention, not true quality. A
          company with no reported findings at all gets no score, which is most manufacturers in
          India.
        </p>
        <p>
          Measured honestly on a year of held-out data never used while building it: the score is
          <strong> statistically indistinguishable from a much simpler linear model</strong> on this
          test window, and is considerably weaker for the roughly half of companies it has never
          seen before (a plain-language caution appears on those scores directly). Every score is
          shown with its own explanation and the reporting-history caveat - never on its own.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">What a result does and doesn&apos;t mean</h2>
        <ul className="list-disc space-y-2 pl-6">
          <li>
            A flagged batch means one specific lot of one specific product was tested and judged not
            of standard quality, or named in a spurious-drug alert, in the month shown - never a
            judgement on the whole product, or on every batch a company has made.
          </li>
          <li>
            A &ldquo;not found&rdquo; result means this exact name and batch don&apos;t appear in
            the archive this site holds. It is <strong>not</strong> a guarantee that the batch is
            safe - CDSCO only reports batches it tested, and most batches are never tested at all.
          </li>
          <li>
            A spurious (counterfeit) finding is never shown with a manufacturer name. The company
            whose product was copied is the victim of a spurious finding, not the party responsible
            for it, and this site never links the two.
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Known limitations</h2>
        <ul className="list-disc space-y-2 pl-6">
          <li>CDSCO&apos;s sampling is not random, and this site cannot correct for that.</li>
          <li>
            The same medicine is often printed under several slightly different spellings in
            CDSCO&apos;s own records, and this site does not merge them - a search can miss a
            differently-spelled match.
          </li>
          <li>
            The risk score only covers a 6-month horizon and says nothing about longer-term
            behaviour.
          </li>
          <li>
            This site covers CDSCO&apos;s own published alerts only - it is not a complete safety
            record for any medicine or manufacturer.
          </li>
        </ul>
      </section>
    </main>
  );
}
