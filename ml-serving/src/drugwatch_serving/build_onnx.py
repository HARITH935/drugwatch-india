"""Export the registered model to ONNX and verify it, refusing to write a model that disagrees.

Plan §9 Phase 8 steps 1-2, and the gate for step 3: the service loads the ONNX file, so if the
conversion changed the predictions the service would quietly serve different numbers from the ones
Phase 7 measured and published in the model card.

The verification runs on the **real test window**, not on random data: a tree ensemble's
disagreement depends on which leaves get hit, and uniform noise exercises paths no manufacturer
ever takes.

Run from ml-serving/, with Postgres and MLflow up:
    uv run --env-file ../.env python -m drugwatch_serving.build_onnx
"""

from pathlib import Path

import numpy as np

from drugwatch_serving import onnx_export, registry

ARTIFACT = Path(__file__).resolve().parents[2] / "artifacts" / "manufacturer_risk.onnx"


def feature_matrix() -> tuple[np.ndarray, list[str]]:
    """The real test rows, read through drugwatch-ml so the column order cannot drift.

    `drugwatch-ml` is a dev-only dependency (see pyproject.toml): this build step needs the
    warehouse, the running service must never touch it.
    """
    from drugwatch_ml import features, splits

    frame = features.load_features()
    _, test = splits.protocol(str(frame["as_of_month"].max()))
    _, test_rows = splits.split(frame, test)
    columns = list(features.FEATURE_COLUMNS)
    return test_rows[columns].to_numpy(dtype="float64"), columns


def main() -> int:
    loaded = registry.load()
    print(f"loaded {loaded.name} v{loaded.version} ({len(loaded.feature_names)} features)")

    matrix, columns = feature_matrix()
    if list(loaded.feature_names) != columns:
        print("REFUSING: the model's feature order differs from the warehouse's")
        print(f"  model:     {list(loaded.feature_names)[:4]}...")
        print(f"  warehouse: {columns[:4]}...")
        return 1
    print(f"verifying on the real test window: {len(matrix):,} rows")

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    onnx_export.convert(loaded.model, len(columns), ARTIFACT)
    size = ARTIFACT.stat().st_size
    print(f"wrote {ARTIFACT.name} ({size / 1024:.0f} KiB)")

    original = loaded.model.predict_proba(matrix)[:, 1]
    runtime = onnx_export.session(ARTIFACT)
    converted = onnx_export.predict(runtime, matrix)

    agreement = onnx_export.verify(original, converted)
    print("\nONNX against the original LightGBM model:")
    print(agreement.line())

    if not (agreement.within_display_tolerance and agreement.order_preserved):
        print("\nREFUSING to keep this export: it does not reproduce the original model.")
        print("A served score must be the score the model card describes.")
        ARTIFACT.unlink(missing_ok=True)
        return 1

    print("\nthe exported model reproduces the original within display tolerance.")
    print(f"artifact: {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
