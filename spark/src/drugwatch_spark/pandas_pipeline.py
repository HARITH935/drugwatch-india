r"""Phase 3 step 9: the same bronze -> silver cleaning, written in pandas.

This exists for the benchmark the plan asks for: *"run the same cleaning job in both on the full
archive; record runtime and peak memory"*. "The same job" is only an honest claim if both really
do the same work, so this module **imports the same logic** rather than reimplementing it:

- the pure Python functions the Spark job wraps in UDFs - `split_combined_cell`,
  `strengths_in`, `split_brand_generic`, `clean_manufacturer_name`, `cluster_variants`;
- the same regex constants - `dosage_form.PATTERNS`, `failure_category.CATEGORIES`;
- the same column list, `build_silver.SILVER_COLUMNS`.

What had to be written twice is only what Spark expressed as `Column` operations: whitespace
cleaning, date parsing, the schema mapping and the de-duplication. `compare.py` then checks the
two outputs match row for row, which is what proves this port faithful.

**One real difference between the engines, handled here deliberately.** Java's `yy` means
2000-2099, so Spark reads `"Apr-95"` as 2095; Python's `%y` means 1969-2068, so it reads 1995.
Spark's value is then dropped by the 1990-2049 plausible-year rule and pandas' is kept - the same
input giving different output. `_java_two_digit_year()` applies Java's rule, so the two agree.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.pandas_pipeline
"""

import re
from collections import Counter

import pandas as pd

from drugwatch_spark.brand_generic import split_brand_generic
from drugwatch_spark.build_silver import PDF_TEXT, PORTAL_TEXT, SILVER_COLUMNS, SPURIOUS
from drugwatch_spark.deduplicate import (
    BATCH_PLACEHOLDER,
    PREFERRED_METHOD,
    PROVENANCE,
    REDUNDANT_DATASET,
)
from drugwatch_spark.dosage_form import INJECTION, PATTERNS
from drugwatch_spark.failure_category import (
    CATEGORIES,
    OTHER,
    SPURIOUS_CATEGORY,
)
from drugwatch_spark.fix_portal_batch import SPLIT_FIELDS, split_combined_cell
from drugwatch_spark.manufacturer_cluster import cluster_variants
from drugwatch_spark.manufacturer_name import clean_manufacturer_name
from drugwatch_spark.parse_dates import PLAUSIBLE_YEARS, PORTAL_DATE_FORMAT
from drugwatch_spark.parse_pdf_dates import FORMATS
from drugwatch_spark.strength import strengths_in

# Java's date patterns, as the same thing in Python. Mapped rather than rewritten so the two
# engines cannot drift apart: a format added to parse_pdf_dates.py shows up here as a KeyError.
JAVA_TO_PYTHON = {
    "MM/yyyy": "%m/%Y",
    "MM/yy": "%m/%y",
    "MMM-yy": "%b-%y",
    "MMM-yyyy": "%b-%Y",
    "dd-MM-yyyy": "%d-%m-%Y",
}
PDF_DATE_FORMATS = [JAVA_TO_PYTHON[fmt] for fmt in FORMATS]
PORTAL_DATE_FORMATS = [JAVA_TO_PYTHON[PORTAL_DATE_FORMAT]]
TWO_DIGIT_YEAR = ("%y",)  # the formats where Java and Python disagree (see the docstring)


# --- the steps Spark expressed as Column operations, written again here -------------------


def normalize_whitespace(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """clean_text.py's rules: the same five substitutions, in the same order."""
    for name in columns:
        if name not in frame.columns:
            continue
        text = frame[name].astype("object")
        present = text.notna()
        cleaned = text[present].astype(str)
        cleaned = cleaned.str.replace(" ", " ", regex=False)  # non-breaking space
        cleaned = cleaned.str.replace(r"(?m)^[ \t]+", "", regex=True)  # a line's leading space
        cleaned = cleaned.str.replace(r"(?m)[ \t]+$", "", regex=True)  # a line's trailing space
        cleaned = cleaned.str.replace(r"[ \t]{2,}", " ", regex=True)  # a run mid-line
        cleaned = cleaned.str.replace(r"^\s+|\s+$", "", regex=True)  # the value's own edges
        text.loc[present] = cleaned
        frame[name] = text
    return frame


def _java_two_digit_year(parsed: pd.Series) -> pd.Series:
    """Java reads a 2-digit year as 2000-2099; Python's %y as 1969-2068. Use Java's rule."""
    before_2000 = parsed.notna() & (parsed.dt.year < 2000)
    if not before_2000.any():
        return parsed
    shifted = parsed.copy()
    shifted.loc[before_2000] = parsed[before_2000] + pd.DateOffset(years=100)
    return shifted


def parse_dates(frame: pd.DataFrame, formats: list[str]) -> pd.DataFrame:
    """`mfg_date_parsed` / `expiry_date_parsed` / `dates_valid`, as the Spark modules produce.

    Tries each format and keeps the first that fits (Spark coalesces try_to_date the same way),
    then drops anything outside the plausible-year range, exactly as plausible_year() does.
    """
    for column in ("mfg_date", "expiry_date"):
        text = frame[column].astype("object").where(frame[column].notna())
        best = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        for fmt in formats:
            missing = best.isna()
            if not missing.any():
                break
            attempt = pd.to_datetime(text[missing], format=fmt, errors="coerce")
            if fmt in TWO_DIGIT_YEAR or fmt.endswith("%y"):
                attempt = _java_two_digit_year(attempt)
            best.loc[missing] = attempt
        low, high = PLAUSIBLE_YEARS
        implausible = best.notna() & ~best.dt.year.between(low, high)
        best.loc[implausible] = pd.NaT
        frame[f"{column}_parsed"] = best.dt.date.where(best.notna())
    mfg, expiry = frame["mfg_date_parsed"], frame["expiry_date_parsed"]
    both = mfg.notna() & expiry.notna()
    frame["dates_valid"] = pd.Series(pd.NA, index=frame.index, dtype="object")
    frame.loc[both, "dates_valid"] = mfg[both] < expiry[both]
    return frame


def fix_combined_manufacturer_cells(frame: pd.DataFrame) -> pd.DataFrame:
    """The 9 portal rows whose manufacturer cell holds all four values (fix_portal_batch.py)."""
    split = frame["manufacturer"].map(split_combined_cell)
    for field in SPLIT_FIELDS:
        found = split.map(lambda values, field=field: values[field])
        frame[field] = found.where(found.notna(), frame[field])
    return frame


def add_dosage_form(frame: pd.DataFrame, name: pd.Series) -> pd.DataFrame:
    """dosage_form.py's rule: exactly one form matches, or a mix that includes Injection."""
    text = name.fillna("")
    matches = {form: text.str.contains(pattern, regex=True, na=False) for form, pattern in PATTERNS}
    found = pd.DataFrame(matches)
    count = found.sum(axis=1)
    # Exactly one form matched: that one. Otherwise Injection if it is among them, else nothing.
    single = found.idxmax(axis=1).where(count == 1)
    injection = pd.Series(INJECTION, index=frame.index).where(found[INJECTION])
    frame["dosage_form"] = single.where(count == 1, injection)
    return frame


def add_strengths(frame: pd.DataFrame, name: pd.Series) -> pd.DataFrame:
    forms = frame["dosage_form"]
    frame["strengths"] = [
        strengths_in(value, form)
        for value, form in zip(name.where(name.notna()), forms.where(forms.notna()), strict=True)
    ]
    return frame


def add_brand_generic(frame: pd.DataFrame, name: pd.Series) -> pd.DataFrame:
    split = name.map(split_brand_generic)
    frame["split_generic_name"] = split.map(lambda value: value["split_generic_name"])
    frame["split_brand_name"] = split.map(lambda value: value["split_brand_name"])
    return frame


def add_clean_manufacturer_name(frame: pd.DataFrame) -> pd.DataFrame:
    split = frame["manufacturer"].map(clean_manufacturer_name)
    frame["manufacturer_name"] = split.map(lambda value: value["manufacturer_name"])
    frame["manufacturer_address"] = split.map(lambda value: value["manufacturer_address"])
    return frame


def add_failure_categories(frame: pd.DataFrame) -> pd.DataFrame:
    """failure_category.py's vocabulary, applied to the same normalised text."""
    text = (
        frame["failure_reason"]
        .astype("object")
        .where(frame["failure_reason"].notna(), "")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .str.lower()
    )
    compiled = [(name, re.compile(pattern)) for name, pattern in CATEGORIES]
    categories = []
    for value, spurious in zip(text, frame["source_dataset"] == SPURIOUS, strict=True):
        found = [name for name, pattern in compiled if pattern.search(value)]
        if value:
            found = found or [OTHER]
        else:
            found = []
        if spurious:
            found = [SPURIOUS_CATEGORY] + [c for c in found if c != SPURIOUS_CATEGORY]
        categories.append(found)
    frame["failure_categories"] = categories
    return frame


# --- the schema mapping and de-duplication ------------------------------------------------


def product_name_of(frame: pd.DataFrame) -> pd.Series:
    """The medicine's name, wherever this source keeps it (build_silver.product_name_of)."""
    if "generic_name" in frame.columns:
        return frame["generic_name"].where(frame["generic_name"].notna(), frame["product_name"])
    return frame["product_name"]


def keep_raw(frame: pd.DataFrame) -> pd.DataFrame:
    for field in ("batch_no", "mfg_date", "expiry_date", "manufacturer"):
        frame[f"{field}_raw"] = frame[field]
    frame["product_name_raw"] = product_name_of(frame)
    return frame


def clean_pdf(frame: pd.DataFrame) -> pd.DataFrame:
    return parse_dates(normalize_whitespace(keep_raw(frame), PDF_TEXT), PDF_DATE_FORMATS)


def clean_portal(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = fix_combined_manufacturer_cells(normalize_whitespace(keep_raw(frame), PORTAL_TEXT))
    # The portal format first, then the PDF formats for what it cannot read: the combined cell's
    # dates are written CDSCO's PDF way (build_silver explains why).
    return parse_dates(cleaned, PORTAL_DATE_FORMATS + PDF_DATE_FORMATS)


def clean_shared(frame: pd.DataFrame) -> pd.DataFrame:
    name = product_name_of(frame)
    frame = add_dosage_form(frame, name)
    frame = add_strengths(frame, name)
    frame = add_brand_generic(frame, name)
    return add_clean_manufacturer_name(frame)


def to_silver_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Map one cleaned source onto the shared silver schema (build_silver.to_silver_columns)."""
    spurious = frame["source_dataset"] == SPURIOUS
    missing = pd.Series(pd.NA, index=frame.index, dtype="object")
    out = pd.DataFrame(
        {
            "source_dataset": frame["source_dataset"],
            "source_key": frame["source_key"],
            "source_sha256": frame["source_sha256"],
            "source_url": frame["source_url"],
            "page": frame["page"] if "page" in frame.columns else missing,
            "row_index": frame["row_index"],
            "alert_month": frame["alert_month"],
            "extraction_method": frame["extraction_method"],
            "batch_no": frame["batch_no"],
            "batch_no_raw": frame["batch_no_raw"],
            "mfg_date_raw": frame["mfg_date_raw"],
            "expiry_date_raw": frame["expiry_date_raw"],
            "mfg_date": frame["mfg_date_parsed"],
            "expiry_date": frame["expiry_date_parsed"],
            "dates_valid": frame["dates_valid"],
            "product_name_raw": frame["product_name_raw"],
            "generic_name": frame["split_generic_name"],
            "brand_name": frame["split_brand_name"],
            "dosage_form": frame["dosage_form"],
            "strengths": frame["strengths"],
            "manufacturer_raw": frame["manufacturer_raw"],
            "manufacturer_name": frame["manufacturer_name"].where(~spurious),
            "manufacturer_address": frame["manufacturer_address"].where(~spurious),
            "is_spurious": spurious,
            "name_on_pack": frame["manufacturer_name"].where(spurious),
            # failure_categories is added after the union, like Spark's: it needs is_spurious.
            "failure_reason": frame["failure_reason"],
            "reported_by": frame["reported_by"],
            "remarks": frame["remarks"] if "remarks" in frame.columns else missing,
            "firm_reply": frame["firm_reply"] if "firm_reply" in frame.columns else missing,
        }
    )
    return out


def add_canonical_manufacturer(frame: pd.DataFrame) -> pd.DataFrame:
    """manufacturer_cluster.py's RapidFuzz clustering, over both sources at once."""
    named = frame["manufacturer_name"].dropna()
    mapping = cluster_variants(Counter(named))
    frame["manufacturer_canonical"] = frame["manufacturer_name"].map(
        lambda value: mapping.get(value) if isinstance(value, str) else None
    )
    return frame


def _batch_key(batch_no: pd.Series) -> pd.Series:
    collapsed = (
        batch_no.astype("object")
        .where(batch_no.notna(), "")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.lower()
        .str.replace(r"^[ .]+|[ .]+$", "", regex=True)
    )
    squashed = (
        batch_no.astype("object")
        .where(batch_no.notna(), "")
        .astype(str)
        .str.replace(r"[^A-Za-z0-9]", "", regex=True)
        .str.upper()
    )
    usable = (squashed != "") & ~collapsed.isin(BATCH_PLACEHOLDER)
    return squashed.where(usable)


def _squashed(values: pd.Series) -> pd.Series:
    out = (
        values.astype("object")
        .where(values.notna(), "")
        .astype(str)
        .str.replace(r"[^A-Za-z0-9]", "", regex=True)
        .str.upper()
    )
    return out.where(out != "")


def deduplicate(frame: pd.DataFrame) -> pd.DataFrame:
    """deduplicate.py's rule: one row per finding, portal preferred, gaps filled from the twin."""
    kept = frame[frame["source_dataset"] != REDUNDANT_DATASET].copy()
    maker = kept["manufacturer_canonical"].where(
        kept["manufacturer_canonical"].notna(), kept["name_on_pack"]
    )
    parts = {
        "batch": _batch_key(kept["batch_no"]),
        "month": kept["alert_month"],
        "maker": _squashed(maker),
        "product": _squashed(kept["product_name_raw"]),
        "spurious": kept["is_spurious"].astype(str),
    }
    complete = pd.concat([part.notna() for part in parts.values()], axis=1).all(axis=1)
    # Built by vectorised concatenation, not a row-wise .agg: pandas 3 keeps missing values as NA
    # through astype(str), so joining per row both breaks on them and is needlessly slow.
    as_text = [part.astype("object").where(part.notna(), "").astype(str) for part in parts.values()]
    together = "k"
    for part in as_text:
        together = together + "\x01" + part
    page_text = kept["page"].astype("object").where(kept["page"].notna(), "-").astype(str)
    alone = (
        "r\x01"
        + kept["source_key"].astype(str)
        + "\x01"
        + page_text
        + "\x01"
        + kept["row_index"].astype(str)
    )
    kept["_finding"] = together.where(complete, alone)
    # Preference: the portal first, then a stable tie-break, exactly as the window does.
    kept["_prefer"] = (kept["extraction_method"] != PREFERRED_METHOD).astype(int)
    kept = kept.sort_values(
        ["_finding", "_prefer", "source_key", "page", "row_index"], na_position="last"
    )

    content = [c for c in frame.columns if c not in PROVENANCE]
    groups = kept.groupby("_finding", sort=False, dropna=False)
    # GroupBy.first() IS "the first non-null value per column", in the sort order above - the
    # same thing Spark's first(ignorenulls=True) over an ordered window does. (An earlier
    # transform(ffill().bfill()) did the same but relied on object-dtype downcasting, which
    # pandas has deprecated, and re-walked every group per column.)
    first_filled = groups[content].first()
    all_keys = groups["source_key"].agg(lambda keys: sorted(set(keys)))

    winners = kept[groups.cumcount() == 0].copy()
    finding = winners["_finding"]
    for column in content:
        winners[column] = first_filled[column].loc[finding].to_numpy()
    winners["also_reported_in"] = [
        sorted(set(keys) - {own})
        for keys, own in zip(all_keys.loc[finding], winners["source_key"], strict=True)
    ]
    return winners.drop(columns=["_finding", "_prefer"])


def build_silver(pdf: pd.DataFrame, portal: pd.DataFrame) -> pd.DataFrame:
    """Both bronze datasets, cleaned and mapped onto one silver table - the pandas way."""
    rows = pd.concat(
        [
            to_silver_columns(clean_shared(clean_pdf(pdf))),
            to_silver_columns(clean_shared(clean_portal(portal))),
        ],
        ignore_index=True,
    )
    categorised = add_failure_categories(rows)
    clustered = add_canonical_manufacturer(categorised)
    return deduplicate(clustered)[SILVER_COLUMNS].reset_index(drop=True)


def read_bronze(path: str, env=None, partitioning: str | None = None) -> pd.DataFrame:
    """One RustFS folder of Parquet as a DataFrame, read with pyarrow.

    `partitioning="hive"` is needed for silver, whose `source_dataset`/`alert_month` live in the
    directory names rather than in the files; bronze is flat and needs none.
    """
    import os

    import pyarrow.dataset as ds
    from pyarrow import fs

    from drugwatch_spark.session import DEFAULT_ENDPOINT

    env = env if env is not None else os.environ
    endpoint = env.get("RUSTFS_ENDPOINT") or DEFAULT_ENDPOINT
    scheme, _, host = endpoint.partition("://")
    filesystem = fs.S3FileSystem(
        access_key=env["RUSTFS_ACCESS_KEY"],
        secret_key=env["RUSTFS_SECRET_KEY"],
        endpoint_override=host,
        scheme=scheme,
        region="us-east-1",
    )
    dataset = ds.dataset(path, filesystem=filesystem, format="parquet", partitioning=partitioning)
    return dataset.to_table().to_pandas()


def main() -> None:
    """Run the pandas pipeline on the real archive and report what it produced."""
    PDF_PATH, PORTAL_PATH = "bronze/cdsco-pdf", "bronze/cdsco-portal"
    pdf = read_bronze(PDF_PATH)
    portal = read_bronze(PORTAL_PATH)
    print(f"bronze: {len(pdf)} PDF rows, {len(portal)} portal rows")
    silver = build_silver(pdf, portal)
    print(f"silver: {len(silver)} rows, {len(silver.columns)} columns")
    print(f"  spurious: {int(silver['is_spurious'].sum())}")
    attributed = silver.loc[silver["is_spurious"], "manufacturer_canonical"].notna().sum()
    print(f"  attributed spurious rows: {int(attributed)} (must be 0)")
    print(f"  distinct manufacturers: {silver['manufacturer_canonical'].nunique()}")
    print(f"  reported by 2+ documents: {int((silver['also_reported_in'].map(len) > 0).sum())}")


if __name__ == "__main__":
    main()
