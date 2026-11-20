"""Prove the Phase 7 foundations work end to end, before any modelling is built on them.

Four things have to be true, and three of them fail silently if they are not:

1. `gold.mart_ml_features` is readable and has the columns the training code expects.
2. The warehouse refuses a write from this project (the read-only guarantee).
3. MLflow records a run with its reproducibility tags.
4. **An artifact survives the round trip to RustFS and back.** This is the one worth testing
   hardest: MLflow accepts `log_artifact` and returns success whether or not the server can
   actually reach its artifact store, so a misconfigured bucket shows up as a model that cannot be
   loaded in Phase 8, long after the run that "succeeded".

Run from ml/, with the stack up and gold loaded:
    uv run --env-file ../.env python -m drugwatch_ml.smoke_test
"""

import json
import tempfile
from pathlib import Path

import psycopg

from drugwatch_ml import features, tracking


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'ok  ' if ok else 'FAIL'}  {label:52s} {detail}")
    return ok


def main() -> int:
    results = []

    frame = features.load_features()
    features.check_columns(frame)
    results.append(
        check(
            "gold.mart_ml_features is readable",
            len(frame) > 0,
            f"{len(frame)} labelled rows x {len(features.FEATURE_COLUMNS)} features",
        )
    )
    results.append(
        check(
            "every feature is numeric, no object columns",
            all(frame[c].dtype.kind in "fiu" for c in features.FEATURE_COLUMNS),
        )
    )
    results.append(
        check(
            "the unknowable labels are excluded",
            bool(frame["label_window_complete"].all()),
            f"newest usable cutoff {frame['as_of_month'].max()}",
        )
    )

    # The read-only guarantee, tested by actually attempting a write.
    refused = False
    try:
        with psycopg.connect(**features.connection_info()) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute("create table ml_smoke_test_should_not_exist (x int)")
    except psycopg.errors.ReadOnlySqlTransaction:
        refused = True
    results.append(check("the warehouse refuses a write from ml/", refused))

    # MLflow: a run, its tags, a metric, and an artifact that has to come back byte for byte.
    payload = {"phase": 7, "purpose": "smoke test of the artifact round trip"}
    run_id = None
    with tracking.start_run("smoke-test", frame, purpose="foundation check") as run:
        run_id = run.info.run_id
        import mlflow

        mlflow.log_param("rows", len(frame))
        mlflow.log_metric("positive_rate", float(frame[features.LABEL_COLUMN].mean()))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "smoke.json"
            source.write_text(json.dumps(payload))
            mlflow.log_artifact(str(source))

    import mlflow

    stored = mlflow.get_run(run_id)
    results.append(
        check(
            "MLflow recorded the run and its tags",
            stored.data.tags.get("git_commit", "unknown") != "unknown"
            and "data_rows" in stored.data.tags,
            f"run {run_id[:8]} commit {stored.data.tags.get('git_commit', '?')[:8]}"
            f" dirty={stored.data.tags.get('git_dirty')}",
        )
    )

    with tempfile.TemporaryDirectory() as directory:
        local = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="smoke.json", dst_path=directory
        )
        came_back = json.loads(Path(local).read_text())
    results.append(
        check(
            "an artifact survived the trip to RustFS and back",
            came_back == payload,
            "written by the server into s3://mlflow/, fetched back through it",
        )
    )

    print()
    if all(results):
        print("Phase 7 foundations are ready")
        return 0
    print("something above is not ready - fix it before training anything")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
