"""Phase 8: serving the manufacturer risk score."""

import os

# Same reason as drugwatch_ml: MLflow prints an authoring hint on import that would land in
# the middle of every service log line.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
