"""Read `gold.mart_ml_features` - the only table Phase 7 trains on.

The mart was built in Phase 4 and verified there against an independent recomputation of every
row: 0 wrong features, 0 wrong labels, 0 leaked labels. This module does not recompute any of it.
It reads, it checks the shape is what the training code expects, and it refuses to hand back rows
whose label the archive cannot know yet.

**Read-only, enforced by the database.** `connection.read_only = True` means Postgres rejects a
write from this session, so no training run can modify the warehouse it learns from. Same
guarantee as `analytics/` (ADR 0013), and the connection code is deliberately duplicated rather
than imported from there: `analytics/` is the exploration project, and a training pipeline that
breaks when a notebook dependency changes would be the wrong coupling.
"""

import os
from collections.abc import Mapping
from typing import Any

import pandas as pd
import psycopg

# Every feature column the model may see, and nothing else. Written out rather than "whatever the
# table has" so that a column added to the mart later cannot silently become a feature - the test
# that compares this list against the live table fails first and someone decides.
FEATURE_COLUMNS: tuple[str, ...] = (
    "reports_3m",
    "reports_6m",
    "reports_12m",
    "reports_24m",
    "reports_prior_6m",
    "reports_trend_6m",
    "months_since_last_report",
    "distinct_drugs_12m",
    "distinct_reporting_states_12m",
    "central_lab_reports_12m",
    "state_lab_reports_12m",
    "central_lab_share_12m",
    "category_mentions_12m",
    "assay_share_12m",
    "dissolution_share_12m",
    "sterility_share_12m",
    "description_share_12m",
    # Plan §12's "share of reports by drug class", available since Phase 6's reviewed vocabulary
    # (ADR 0014). Shares of class MENTIONS, so they do not sum to 1 - a combination product
    # belongs to two to four classes. Only the seven classes above 5% of the archive get a column;
    # a share of a 2%-class over one company's 12-month window is almost always exactly 0 or 1.
    "class_mentions_12m",
    "distinct_drug_classes_12m",
    "antibiotic_share_12m",
    "analgesic_share_12m",
    "gastrointestinal_share_12m",
    "vitamin_share_12m",
    "respiratory_share_12m",
    "cardiovascular_share_12m",
    "antihistamine_share_12m",
    "unclassified_share_12m",
    # This company's share of everything the archive reported in the window. A ratio, never the
    # raw archive volume: that correlates 0.855 with calendar time, and since the test period is
    # strictly later than training, "recent means positive" would score well for the wrong reason
    # and would read as a real finding in SHAP.
    "share_of_archive_reports_12m",
)

# Not features: the keys identify a row, the label is the answer, and `label_window_complete` is
# the reason a row is usable. Letting any of these into the matrix would be a leak.
KEY_COLUMNS: tuple[str, ...] = ("manufacturer_id", "as_of_month", "as_of_month_start")
LABEL_COLUMN = "label_reported_next_6m"


def connection_info(env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Connection settings from the environment. The password is never defaulted."""
    return {
        "host": env.get("POSTGRES_HOST", "localhost"),
        "port": int(env.get("POSTGRES_PORT", "5433")),
        "dbname": env.get("POSTGRES_DB", "drugwatch"),
        "user": env.get("POSTGRES_USER", "drugwatch"),
        "password": env["POSTGRES_PASSWORD"],
        "connect_timeout": 10,
    }


def query(sql: str, params: tuple[Any, ...] | None = None) -> pd.DataFrame:
    """Run one SELECT in a read-only transaction."""
    with psycopg.connect(**connection_info()) as connection:
        connection.read_only = True  # the database refuses any write from this session
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [column.name for column in cursor.description or []]
            return pd.DataFrame(cursor.fetchall(), columns=columns)


def load_features(*, labelled_only: bool = True) -> pd.DataFrame:
    """The feature table, as rows the training code may use.

    `labelled_only` drops the cutoffs whose 6-month future runs past the end of the archive. Those
    rows have `label_reported_next_6m = null` and nothing may fill them in: an unknown future is
    not a negative outcome, and treating it as one would teach the model that the most recent
    months are always quiet. They are kept available because scoring a *current* manufacturer uses
    exactly those rows - features known now, outcome not yet knowable.
    """
    wanted = (*KEY_COLUMNS, *FEATURE_COLUMNS, LABEL_COLUMN, "label_window_complete")
    # The column names are module constants, not input - but the query is still assembled as text,
    # so they are checked to be plain identifiers rather than trusted for being constants. This is
    # what makes the S608 suppression below a statement rather than a silencing.
    if not all(name.isidentifier() for name in wanted):
        raise ValueError(f"column names must be plain identifiers: {wanted}")
    columns = ", ".join(wanted)
    where = "where label_window_complete" if labelled_only else ""
    # noqa on the f-string itself: it interpolates only the identifiers checked above.
    sql = f"select {columns} from gold.mart_ml_features {where} order by as_of_month"  # noqa: S608
    frame = query(sql)

    # Postgres numerics arrive as Decimal, which LightGBM cannot use and which silently becomes an
    # object column in pandas. Converted once, here, rather than in each caller.
    for column in FEATURE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
    if labelled_only:
        frame[LABEL_COLUMN] = frame[LABEL_COLUMN].astype("int8")
    return frame


def check_columns(frame: pd.DataFrame) -> None:
    """Refuse a feature table whose shape is not the one this code was written against.

    The failure this prevents is quiet: a renamed or dropped mart column would otherwise reach
    LightGBM as a column of nulls, train without complaining, and score every manufacturer with a
    feature that means nothing.
    """
    missing = [column for column in (*KEY_COLUMNS, *FEATURE_COLUMNS) if column not in frame.columns]
    if missing:
        raise ValueError(f"gold.mart_ml_features is missing expected column(s): {missing}")
    if LABEL_COLUMN not in frame.columns:
        raise ValueError(f"the label column {LABEL_COLUMN!r} is not in the frame")
