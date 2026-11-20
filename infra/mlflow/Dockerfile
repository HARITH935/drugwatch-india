# MLflow's official image carries MLflow and nothing to connect it to anything.
#
# Checked on ghcr.io/mlflow/mlflow:v3.18.0 (Python 3.11.18): `psycopg2` and `boto3` are both
# absent, so the server cannot reach its Postgres backend store or its RustFS artifact store as
# shipped. Same situation as Superset (infra/superset/Dockerfile), and the same fix: add exactly
# the two drivers, pinned, and nothing else.
FROM ghcr.io/mlflow/mlflow:v3.18.0

# psycopg2-binary: the backend store (experiments, runs, metrics, the model registry).
# boto3: the artifact store, which is RustFS over the S3 API.
# --no-cache-dir keeps the wheel cache out of the image layer.
RUN pip install --no-cache-dir psycopg2-binary==2.9.13 boto3==1.44.7

# RustFS requires path-style S3 addressing (ADR 0002): the bucket goes in the path, not in the
# hostname. boto3 defaults to virtual-host style and there is no official environment variable for
# this - `addressing_style` is read from the AWS config file - so the setting is baked into the
# image rather than passed in, where it would silently fail to apply.
RUN mkdir -p /root/.aws \
 && printf '[default]\ns3 =\n    addressing_style = path\n' > /root/.aws/config
