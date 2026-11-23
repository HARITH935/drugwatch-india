"""Shared fixtures. The integration test needs the local MLflow server."""

import pytest


@pytest.fixture
def mlflow_available():
    """Skip unless the tracking server answers."""
    import urllib.error
    import urllib.request

    from drugwatch_llm.tracking import tracking_uri

    try:
        urllib.request.urlopen(f"{tracking_uri()}/health", timeout=5)  # noqa: S310 - local URL
    except (urllib.error.URLError, OSError) as error:
        pytest.skip(f"no MLflow server at {tracking_uri()}: {error}")
