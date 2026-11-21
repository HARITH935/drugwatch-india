# The manufacturer risk score service (Phase 8).
#
# Build context is the REPO ROOT, not ml-serving/: this project depends on ../ml for the approved
# explanation wording (see ml-serving/pyproject.toml), so both have to be inside the context and
# keep their relative layout.
FROM python:3.13-slim

# libgomp1 is LightGBM's OpenMP runtime. Without it `import lightgbm` fails at container start
# with a bare "libgomp.so.1: cannot open shared object file", which looks like a Python problem
# and is not one. It is the same dependency `brew install libomp` provides on the Mac.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

# uv, pinned, from the official image - the same tool and version the projects are locked with.
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency manifests first, so a code change does not re-resolve and re-download everything.
COPY ml/pyproject.toml ml/uv.lock ./ml/
COPY ml-serving/pyproject.toml ml-serving/uv.lock ./ml-serving/
# uv needs the package directories to exist to build the local projects.
RUN mkdir -p ml/src/drugwatch_ml ml-serving/src/drugwatch_serving \
 && touch ml/src/drugwatch_ml/__init__.py ml-serving/src/drugwatch_serving/__init__.py

# --no-dev: the container gets no pytest, no ruff, and no httpx. --frozen: install exactly the
# lockfile, never re-resolve during a build - a container that resolves is a container whose
# dependencies can change between two builds of the same commit.
RUN cd ml-serving && uv sync --no-dev --frozen

COPY ml/src ./ml/src
COPY ml-serving/src ./ml-serving/src

WORKDIR /app/ml-serving

# A non-root user: the service needs no write access to anything, and ADR-level caution about a
# container that is exposed in Phase 12 costs nothing here.
RUN useradd --create-home --uid 10001 serving && chown -R serving /app
USER serving

ENV PATH="/app/ml-serving/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MLFLOW_DISABLE_AGENT_HINT=1

EXPOSE 8000

# One worker on purpose: each worker loads its own copy of the model and its own SHAP explainer,
# so four workers would be four copies of everything for a service whose load is a handful of
# requests per page view. Phase 12 can raise it with measurements behind the change.
CMD ["uvicorn", "drugwatch_serving.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
