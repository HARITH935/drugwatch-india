"""Phase 3 step 4, piece 1: dosage form (Tablet, Capsule, Injection...) from the product name.

Every rule here was checked against all 8,322 real names (PDF product_name, portal NSQ
generic_name, portal spurious product_name) before it was added, 2026-11-13:

- A fixed vocabulary of dosage-form words, matched as whole words in any case. With it, 86.9% of
  names mention exactly one form, the clean case.
- Short abbreviations count too (Tab, Caps, Inj.): checked one by one, all 101 rows matched ONLY by
  an abbreviation are genuine ("Telmisartan Tab IP 40 mg", "Gentamicin Inj. IP"). The one false hit
  found was an abbreviation glued to a brand by a hyphen ("NS-CAP Sodium Chloride Injection" is not
  a capsule), so an abbreviation right after a hyphen is ignored.
- Several forms in one name -> None, except one proven rule: if Injection is one of them, the
  product is an Injection. All 62 distinct real names of that kind say so themselves ("Solution
  for Injection", "Emulsion for Injection", "Powder for Injection", "Intravenous Infusion").
  Other mixes ("Ophthalmic Solution (Eye Drops)", "Oral Suspension (... Liquid)") stay None: no
  rule for them has been checked yet, and a missing value is better than a wrong one.
- No form word -> None. Mostly correct (vaccines, syringes, cotton, bandages, sanitizers carry no
  dosage form in the name); a few are CDSCO typos ("Tables", "Caspules") left for later.
- Not in the vocabulary on purpose: "Sachet" (packaging, not a form: "Granule Sachet" is Granules)
  and "Respules"/"Rotacaps" (device brand names).

Adds `dosage_forms_found` (every form word seen, in FORMS order, so a None can always be
explained) and `dosage_form` (the one form, or None).

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.dosage_form
"""

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

# (form, whole words, short abbreviations or None). Regex pieces, matched case-insensitively.
FORMS = (
    ("Tablet", r"tablets?", r"tabs?"),
    ("Capsule", r"capsules?", r"caps?"),
    ("Injection", r"injections?|infusions?", r"inj"),
    ("Syrup", r"syrups?", None),
    ("Suspension", r"suspensions?", None),
    ("Solution", r"solutions?", None),
    ("Drops", r"drops?", None),
    ("Cream", r"creams?", None),
    ("Ointment", r"ointments?", None),
    ("Gel", r"gels?", None),  # \b keeps "Gelatin" out
    ("Lotion", r"lotions?", None),
    ("Powder", r"powders?", None),
    ("Granules", r"granules?", None),
    ("Spray", r"sprays?", None),
    ("Inhaler", r"inhalers?", None),
    ("Lozenge", r"lozenges?", None),
    ("Suppository", r"suppositor(?:y|ies)", None),
    ("Liquid", r"liquids?", None),
    ("Elixir", r"elixirs?", None),
    ("Emulsion", r"emulsions?", None),
    ("Soap", r"soaps?", None),
    ("Shampoo", r"shampoos?", None),
    ("Bolus", r"bolus(?:es)?", None),  # veterinary: a large tablet for animals
)
INJECTION = "Injection"


def form_pattern(words: str, abbreviations: str | None) -> str:
    """One Java regex: the whole words, or an abbreviation not glued to a brand by a hyphen."""
    pattern = rf"(?i)\b(?:{words})\b"
    if abbreviations:
        pattern += rf"|(?<!-)\b(?:{abbreviations})\b"  # (?<!-): "NS-CAP" is a brand, not a capsule
    return pattern


PATTERNS = tuple((form, form_pattern(words, abbrev)) for form, words, abbrev in FORMS)


def add_dosage_form(df: DataFrame, name: Column) -> DataFrame:
    # One entry per form: the form's name if it appears in `name`, else null; nulls then dropped.
    found = F.array_compact(F.array(*(F.when(name.rlike(p), F.lit(f)) for f, p in PATTERNS)))
    with_found = df.withColumn("dosage_forms_found", found)
    forms = F.col("dosage_forms_found")
    return with_found.withColumn(
        "dosage_form",
        F.when(F.size(forms) == 1, forms[0]).when(
            F.array_contains(forms, INJECTION), F.lit(INJECTION)
        ),  # anything else (none, or a mix without Injection) stays null
    )


def main() -> None:
    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("dosage-form")
    try:
        pdf = add_dosage_form(read_bronze(spark, PDF), F.col("product_name"))
        # NSQ rows keep the name in generic_name, spurious rows in product_name; never both.
        portal = read_bronze(spark, PORTAL)
        portal = add_dosage_form(portal, F.coalesce(F.col("generic_name"), F.col("product_name")))

        for label, df in (("PDF", pdf), ("Portal", portal)):
            total = df.count()
            n_found = F.size("dosage_forms_found")
            one = df.where(n_found == 1).count()
            by_rule = df.where((n_found > 1) & F.col("dosage_form").isNotNull()).count()
            mixed = df.where((n_found > 1) & F.col("dosage_form").isNull()).count()
            none = df.where(n_found == 0).count()
            print(f"\n{label}: {total} rows")
            print(f"  one form            {one:5} ({one / total:.1%})")
            print(f"  Injection rule      {by_rule:5} ({by_rule / total:.1%})")
            print(f"  mixed, left null    {mixed:5} ({mixed / total:.1%})")
            print(f"  no form word, null  {none:5} ({none / total:.1%})")
            counts = df.groupBy("dosage_form").count().orderBy(F.desc("count")).collect()
            print("  by form:", ", ".join(f"{r['dosage_form']}={r['count']}" for r in counts))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
