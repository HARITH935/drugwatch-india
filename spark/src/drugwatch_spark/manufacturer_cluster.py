"""Phase 3 step 5, piece 2: cluster manufacturer spelling variants with RapidFuzz.

Works on `manufacturer_name` from piece 1 (manufacturer_name.py), never on the raw field, which
still has the postal address stuck to it.

CLAUDE.md Section 5: "A missed merge is better than a wrong merge." Everything below is chosen to
err that way, and was checked against all 3,320 real distinct names first (2026-11-13):

- Scorer: `fuzz.token_sort_ratio` with RapidFuzz's own `default_process` (lower-cases and strips
  punctuation), so case and "Private.Limited" vs "Private Limited" cost nothing. token_sort_ratio
  also forgives word order; token_set_ratio was NOT used - it ignores extra words entirely, so
  "Nest Healthcare" and "Nest Healthcare Plot No.: 300" would score 100 and might be two
  different units of one company.

- Threshold 98, chosen by reading real pairs in every band, not picked by feel:
    98-100 (189 pairs): every sampled pair was the same company - plural/singular
           ("Formulation"/"Formulations"), punctuation, case, OCR noise ("Relief"/"Relif",
           "Healer's"/"Healer?s"), or a stray page number ("... Limited 111").
    95-98  (260 pairs): mixed. Real matches ("UPKAR PHARMACEUTIALS"/"Upkar Pharmaceuticals") sit
           next to clear false ones - "RPL (INDIA) Pharmaceuticals Private Limited" vs "ZRS
           Pharmaceuticals India Private Limited" scores 95.1 but is two different companies.
    92-95 and below: mostly false. Different companies share the generic tail ("X Pharmaceuticals
           Private Limited"), so "Sarv"/"Solar", "PRS"/"Pulse", "Inven"/"Kinesis" all score 92+.
  So 98+ merges automatically; 95-98 is for piece 3 (Harith reviews those by hand); below 95 is
  not merged and not offered for review.

- Clustering: connected components (union-find) over the 98+ pairs, because similarity is not
  transitive. Checked every resulting cluster of 3+ for bad chaining - all were coherent, e.g. 8
  spellings of "J.M. Laboratories" and 8 of "Martin & Brown Bio-Sciences Private Limited".
  Conservative on purpose: 3 separate Martin & Brown clusters stay separate, because one carries
  a leftover address fragment ("K.No. 918/419") and one has no "Private Limited". Piece 3's
  review is where those get joined up, by a person, not by lowering the threshold.

- Canonical name: the variant on the most rows, then the one that is not ALL CAPS or all
  lower-case, then alphabetical (a stable tie-break; the top count is tied in 126 of 436 real
  clusters, and the casing rule decides 6 of them, always in favour of the readable spelling).

Size: 3,320 real names take ~6 s and hold only the pairs above the cutoff (818 of them), not a
full n x n matrix - see pairs_scoring(). A much larger archive would want blocking (compare only
names sharing a first letter or token) before the comparison count becomes the limit.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.manufacturer_cluster
"""

from collections import defaultdict

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from rapidfuzz import fuzz, process, utils

THRESHOLD = 98  # merge automatically at or above this; 95-98 goes to piece 3's human review
REVIEW_FLOOR = 95  # below this, not merged and not offered for review
SCORER = fuzz.token_sort_ratio


def pairs_scoring(
    names: list[str], floor: float, ceiling: float = 101
) -> list[tuple[int, int, float]]:
    """(i, j, score) for every pair of names scoring in [floor, ceiling), each pair once.

    process.extract with a score_cutoff, not process.cdist: cdist needs numpy and builds a full
    n x n matrix (44 MB for 3,320 names, and 100x that if the archive grew 10x), while this keeps
    only the pairs that actually score high enough. Checked: both return exactly the same 818
    pairs at >= 98 on the real archive, in 5.6 s instead of 3 s.
    """
    found = {}
    for i, name in enumerate(names):
        matches = process.extract(
            name, names, scorer=SCORER, processor=utils.default_process,
            score_cutoff=floor, limit=None,
        )  # fmt: skip
        for _, score, j in matches:
            if i != j and score < ceiling:
                found[(min(i, j), max(i, j))] = score
    return [(i, j, score) for (i, j), score in found.items()]


def _components(size: int, edges: list[tuple[int, int, float]]) -> dict[int, list[int]]:
    """Connected components over the given pairs, by union-find."""
    parent = list(range(size))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    for i, j, _ in edges:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    groups = defaultdict(list)
    for i in range(size):
        groups[find(i)].append(i)
    return groups


def canonical_for(variants: list[str], counts: dict[str, int]) -> str:
    """The variant on the most rows; then one that isn't ALL CAPS or all lower-case; then
    alphabetical, so the choice never depends on dict or Spark ordering."""

    def rank(name: str) -> tuple[int, bool, str]:
        letters = [c for c in name if c.isalpha()]
        one_case = bool(letters) and (
            all(c.isupper() for c in letters) or all(c.islower() for c in letters)
        )
        return (-counts[name], one_case, name)

    return min(variants, key=rank)


def cluster_variants(counts: dict[str, int], threshold: int = THRESHOLD) -> dict[str, str]:
    """Map every name to its cluster's canonical name (a name on its own maps to itself)."""
    names = sorted(counts)  # sorted so the result never depends on input order
    if not names:
        return {}
    groups = _components(len(names), pairs_scoring(names, floor=threshold))
    mapping = {}
    for members in groups.values():
        variants = [names[i] for i in members]
        canonical = canonical_for(variants, counts)
        for variant in variants:
            mapping[variant] = canonical
    return mapping


def review_candidates(
    counts: dict[str, int], floor: int = REVIEW_FLOOR, ceiling: int = THRESHOLD
) -> list[tuple[str, str, float]]:
    """Pairs scoring in [floor, ceiling) - too close to ignore, too risky to merge without a
    person looking. Piece 3's input; this module never merges them.

    The score keeps one decimal: rounding it to a whole number prints a 97.56 pair as "98", which
    reads as if it contradicts the band it is listed under."""
    names = sorted(counts)
    rows = [
        (names[i], names[j], round(score, 1))
        for i, j, score in pairs_scoring(names, floor=floor, ceiling=ceiling)
    ]
    return sorted(rows, key=lambda row: (-row[2], row[0], row[1]))


def add_canonical_manufacturer(df: DataFrame, name: Column) -> DataFrame:
    """Add `manufacturer_canonical`: the cluster's agreed name, or the name itself when it has no
    variants. Null stays null (a placeholder manufacturer from piece 1)."""
    counts = {
        row["name"]: row["count"]
        for row in df.select(name.alias("name"))
        .where(name.isNotNull())
        .groupBy("name")
        .count()
        .collect()  # fmt: skip
    }
    mapping = cluster_variants(counts)
    if not mapping:
        return df.withColumn("manufacturer_canonical", F.lit(None).cast("string"))
    lookup = df.sparkSession.createDataFrame(
        list(mapping.items()), "manufacturer_name_key string, manufacturer_canonical string"
    )
    return df.join(
        F.broadcast(lookup), name == F.col("manufacturer_name_key"), "left"
    ).drop("manufacturer_name_key")  # fmt: skip


def main() -> None:
    from drugwatch_spark.manufacturer_name import add_clean_manufacturer_name
    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("manufacturer-cluster")
    try:
        both = None
        for path in (PDF, PORTAL):
            cleaned = add_clean_manufacturer_name(read_bronze(spark, path), F.col("manufacturer"))
            names = cleaned.select("manufacturer_name")
            both = names if both is None else both.union(names)
        named = both.where(F.col("manufacturer_name").isNotNull()).cache()

        counts = {
            row["manufacturer_name"]: row["count"]
            for row in named.groupBy("manufacturer_name").count().collect()
        }
        mapping = cluster_variants(counts)
        merged = {name: c for name, c in mapping.items() if name != c}
        canonicals = set(mapping.values())
        print(f"{named.count()} rows, {len(counts)} distinct names")
        print(f"-> {len(canonicals)} manufacturers after merging {len(merged)} spelling variants")

        groups = defaultdict(list)
        for variant, canonical in mapping.items():
            if variant != canonical:
                groups[canonical].append(variant)
        print("\nbiggest merges:")
        for canonical, variants in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"  {canonical!r} ({counts[canonical]} rows)")
            for variant in sorted(variants, key=lambda v: -counts[v])[:4]:
                print(f"      <- {variant!r} ({counts[variant]})")

        candidates = review_candidates(counts)
        band = f"[{REVIEW_FLOOR}, {THRESHOLD})"
        print(f"\n{len(candidates)} pairs in {band} for piece 3's review, e.g.:")
        for left, right, score in candidates[:5]:
            print(f"  {score}  {left!r} | {right!r}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
