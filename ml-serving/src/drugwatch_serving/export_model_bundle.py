"""`python -m drugwatch_serving.export_model_bundle` - run once on the Mac, with MLflow up.

Phase 12 (ADR 0021): the Hugging Face Space the risk service runs on in production has no MLflow
to call. This writes the registered model into `ml-serving/artifacts/model-bundle/` (git-ignored,
same as every other model weight in this repo), which `infra/ml-serving/Dockerfile.space` then
COPYs into the image. Re-run this and rebuild the image whenever `publish` registers a new
`production` alias.
"""

from pathlib import Path

from drugwatch_serving import registry

BUNDLE_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "model-bundle"


def main() -> int:
    registry.export_bundle(BUNDLE_DIR)
    loaded = registry.load_local(BUNDLE_DIR)
    print(f"exported {loaded.name} version {loaded.version} (run {loaded.run_id})")
    print(f"features: {len(loaded.feature_names)}")
    print(f"bundle: {BUNDLE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
