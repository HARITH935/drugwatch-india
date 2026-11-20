"""Phase 7: the manufacturer risk score."""

import os

# MLflow prints a hint about loading an authoring skill on every import. It is addressed at
# coding assistants, not at this pipeline, and it would otherwise appear in the middle of
# every training log. Set here because this module runs before any entry point imports mlflow.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
