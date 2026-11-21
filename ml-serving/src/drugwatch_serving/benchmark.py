"""Latency of the running service: p50/p95/p99, under concurrency.

Plan §9 Phase 8 step 5. Three things this measures that a single average would hide:

- **`/predict` and `/explain` separately.** SHAP walks every tree path for one row, so an
  explanation cannot be as fast as a score. Reporting one blended number would make the fast path
  look slow and hide whether the slow one is acceptable.
- **A batch of 100 against 100 single requests.** Per-request overhead - HTTP, JSON, an ONNX call
  - dominates at this model size, so the batch endpoint is the one Phase 9 should use for a page
  that scores a list.
- **p95 and p99, not the mean.** A mean hides the tail, and a page waits for its slowest call.

Uses only the standard library, so the numbers are not partly a measurement of an HTTP client the
service does not use.

Run from ml-serving/, against a running service:
    uv run python -m drugwatch_serving.benchmark --url http://localhost:8000
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(url: str, payload: dict | None = None, timeout: float = 30.0) -> tuple[float, int]:
    """One request. Returns (seconds, status). Errors are returned, never raised: a benchmark that
    dies on the first 500 tells you nothing about the other 999."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - a fixed localhost URL
        url, data=data, headers={"Content-Type": "application/json"} if data else {}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            response.read()
            return time.perf_counter() - started, response.status
    except urllib.error.HTTPError as error:
        return time.perf_counter() - started, error.code
    except OSError:
        return time.perf_counter() - started, 0


def percentiles(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "mean": statistics.fmean(ordered),
        "max": ordered[-1],
    }


def report(label: str, samples: list[float], failures: int, requests: int) -> dict:
    stats = percentiles(samples)
    print(
        f"  {label:38s} p50 {stats['p50'] * 1000:7.1f}ms  p95 {stats['p95'] * 1000:7.1f}ms"
        f"  p99 {stats['p99'] * 1000:7.1f}ms  max {stats['max'] * 1000:7.1f}ms"
        + (f"  ({failures} failed of {requests})" if failures else "")
    )
    return {"label": label, "requests": requests, "failures": failures, **stats}


def run(url: str, payload: dict | None, count: int, workers: int) -> tuple[list[float], int]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(lambda _: call(url, payload), range(count)))
    samples = [seconds for seconds, status in outcomes]
    failures = sum(1 for _, status in outcomes if status != 200)
    return samples, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=300)
    args = parser.parse_args()

    health = call(f"{args.url}/health")
    if health[1] != 200:
        print(f"the service is not answering at {args.url} (status {health[1]})")
        return 1
    with urllib.request.urlopen(f"{args.url}/health", timeout=10) as response:  # noqa: S310
        info = json.loads(response.read())
    print(f"{info['model']} v{info['version']}, {info['features']} features, at {args.url}\n")

    # A realistic row: a company with history, which exercises deeper tree paths than all-zeros.
    row = dict.fromkeys(_feature_names(args.url, info["features"]), 0.0)
    row["reports_24m"] = 19.0
    row["reports_12m"] = 8.0
    row["reports_6m"] = 3.0
    row["months_since_last_report"] = 0.0
    row["distinct_reporting_states_12m"] = 5.0

    results = []
    print("sequential (one at a time - the latency a single page sees):")
    for label, path, payload, count in (
        ("/health", "/health", None, args.requests),
        ("/predict, 1 row", "/predict", {"rows": [row]}, args.requests),
        ("/predict, 100 rows in one call", "/predict", {"rows": [row] * 100}, 50),
        ("/explain, 1 row", "/explain", {"features": row}, max(50, args.requests // 6)),
    ):
        samples, failures = run(f"{args.url}{path}", payload, count, workers=1)
        results.append(report(label, samples, failures, count))

    print("\nconcurrent (8 at a time - the tail under load):")
    for label, path, payload in (
        ("/predict, 1 row", "/predict", {"rows": [row]}),
        ("/explain, 1 row", "/explain", {"features": row}),
    ):
        count = args.requests if "predict" in path else max(50, args.requests // 6)
        samples, failures = run(f"{args.url}{path}", payload, count, workers=8)
        results.append(report(f"{label} x8", samples, failures, count))

    single = next(r for r in results if r["label"] == "/predict, 1 row")
    batch = next(r for r in results if r["label"] == "/predict, 100 rows in one call")
    per_row = batch["p50"] / 100
    print(
        f"\nper-row cost: {single['p50'] * 1000:.1f}ms alone against"
        f" {per_row * 1000:.2f}ms inside a 100-row batch"
        f" ({single['p50'] / per_row:.0f}x) - so a page scoring a list should send one batch."
    )
    print(json.dumps(results, indent=2)[:0] or "", end="")
    return 0


def _feature_names(url: str, expected: int) -> list[str]:
    """The model's feature names, taken from the service's own error message rather than hardcoded
    - so this script cannot drift from the model the way a copied list would."""
    _, status = call(f"{url}/predict", {"rows": [{"not_a_feature": 0.0}]})
    if status != 422:
        raise RuntimeError(f"expected a 422 listing the features, got {status}")
    request = urllib.request.Request(  # noqa: S310
        f"{url}/predict",
        data=json.dumps({"rows": [{"not_a_feature": 0.0}]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=10)  # noqa: S310
    except urllib.error.HTTPError as error:
        detail = json.loads(error.read())["detail"]
        names = detail["missing"]
        if len(names) != expected:
            raise RuntimeError(
                f"expected {expected} features, the service named {len(names)}"
            ) from error
        return names
    raise RuntimeError("the service accepted an invalid request")


if __name__ == "__main__":
    raise SystemExit(main())
