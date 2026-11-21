"""What the deployed service must and must not have, read from the compose file itself.

ADR 0017's central claim is that the risk service never reads the warehouse. That is an
architectural promise, and a promise with nothing checking it is a comment. These tests read
`docker-compose.yml` so the promise fails here rather than during a Phase 12 incident.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "docker-compose.yml"
DOCKERFILE = REPO / "infra" / "ml-serving" / "Dockerfile"


@pytest.fixture(scope="module")
def risk_api_block() -> str:
    """The `risk-api:` service's own lines, up to the next service at the same indentation."""
    text = COMPOSE.read_text()
    start = text.index("\n  risk-api:")
    remainder = text[start + 1 :]
    lines = [remainder.splitlines()[0]]
    for line in remainder.splitlines()[1:]:
        if line and not line.startswith("    ") and not line.startswith("  #"):
            break
        lines.append(line)
    return "\n".join(lines)


def test_the_service_is_given_no_database_credentials(risk_api_block):
    """ADR 0017: the service takes features in the request body. Phase 9's API reads gold and
    posts what it read. Credentials here would mean a prediction endpoint that shares the
    warehouse's failure modes - and a second place a password can leak."""
    for forbidden in ("POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_HOST", "POSTGRES_DB"):
        assert forbidden not in risk_api_block, f"risk-api must not receive {forbidden}"


def test_the_service_is_given_no_object_store_credentials(risk_api_block):
    """MLflow proxies artifacts (ADR 0016), so the service needs the tracking URL and nothing
    else. S3 keys here would undo that."""
    for forbidden in ("RUSTFS_ACCESS_KEY", "RUSTFS_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"):
        assert forbidden not in risk_api_block


def test_the_service_reaches_mlflow_by_service_name(risk_api_block):
    """Not localhost:5050, which is only how the port is published to the Mac."""
    assert "MLFLOW_TRACKING_URI: http://mlflow:5000" in risk_api_block


def test_the_service_waits_for_mlflow_to_be_healthy(risk_api_block):
    """No registry means no model, so starting first is a crash rather than a degraded start."""
    assert "mlflow:" in risk_api_block
    assert "condition: service_healthy" in risk_api_block


def test_the_port_is_bound_to_localhost_only(risk_api_block):
    """Same rule as every other service here: reachable from this Mac, not from the Wi-Fi."""
    assert '"127.0.0.1:8000:8000"' in risk_api_block


def test_the_image_installs_the_openmp_runtime():
    """Without libgomp1, `import lightgbm` fails at container start with
    `libgomp.so.1: cannot open shared object file` - which reads like a Python packaging problem
    and is not one."""
    assert "libgomp1" in DOCKERFILE.read_text()


def test_the_build_is_frozen_and_excludes_dev_dependencies():
    """--frozen: a container that re-resolves is a container whose dependencies can change between
    two builds of the same commit. --no-dev: no pytest or ruff in a deployed image."""
    dockerfile = DOCKERFILE.read_text()
    assert "--frozen" in dockerfile
    assert "--no-dev" in dockerfile


def test_the_container_does_not_run_as_root():
    assert "USER serving" in DOCKERFILE.read_text()


def test_mlflow_allows_the_service_name_as_a_host():
    """MLflow 3 rejects an unrecognised Host header as DNS-rebinding protection, and its default
    list does not include a compose service name - so `risk-api` calling http://mlflow:5000 got a
    403 until this was set. Named explicitly rather than disabled."""
    text = COMPOSE.read_text()
    assert "--allowed-hosts" in text
    assert "mlflow:5000" in text
