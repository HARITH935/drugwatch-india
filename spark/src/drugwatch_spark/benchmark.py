r"""Phase 3 step 9: time and measure the same cleaning job in PySpark and in pandas.

`compare_engines.py` proves the two produce identical silver (7,128 rows x 32 columns agree
exactly), so this measures the cost of the same work rather than two different jobs.

**How it measures, and why:**

- **Each engine runs in its own subprocess.** Spark's work happens in a JVM that the Python
  process cannot see, so measuring from inside would miss most of it; and one engine's heap
  would pollute the other's figure if they shared a process.
- **Peak memory is sampled across the whole process tree** (the Python driver *and* its JVM
  child), every 100 ms, taking the maximum. `resource.getrusage` only reports children that have
  been waited for, which misses a JVM still running.
- **Two times are reported.** `pipeline` is the work itself; `total` includes interpreter and
  JVM start-up and jar resolution. Start-up is a real cost that a monthly Airflow task pays
  every run, so hiding it would flatter Spark.
- **Both read bronze from RustFS and write silver as Parquet to a local temp directory.** Writing
  forces each engine to actually materialise every row (a lazy engine can otherwise "finish"
  without doing the work), while keeping object-store write behaviour out of the comparison.

Run (from spark/, RustFS up):
    uv run --env-file ../.env python -m drugwatch_spark.benchmark            # both, once each
    uv run --env-file ../.env python -m drugwatch_spark.benchmark --repeat 3 # median of 3
    uv run --env-file ../.env python -m drugwatch_spark.benchmark --engine pandas  # one child
"""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PDF_PATH = "bronze/cdsco-pdf"
PORTAL_PATH = "bronze/cdsco-portal"
SAMPLE_SECONDS = 0.1


# --- the two engines, each run inside a child process ------------------------------------


def run_pandas(out_dir: str) -> dict:
    """Read bronze, clean it, write silver - all in pandas."""
    from drugwatch_spark.pandas_pipeline import build_silver, read_bronze

    started = time.perf_counter()
    pdf = read_bronze(PDF_PATH)
    portal = read_bronze(PORTAL_PATH)
    silver = build_silver(pdf, portal)
    silver.to_parquet(Path(out_dir) / "silver.parquet", index=False)
    return {"pipeline_seconds": time.perf_counter() - started, "rows": len(silver)}


def run_spark(out_dir: str) -> dict:
    """The same job through PySpark, reading RustFS over S3A."""
    from drugwatch_spark.build_silver import build_silver
    from drugwatch_spark.read_bronze import PDF, PORTAL, read_bronze
    from drugwatch_spark.session import spark_session

    spark = spark_session("benchmark")
    try:
        started = time.perf_counter()
        silver = build_silver(read_bronze(spark, PDF), read_bronze(spark, PORTAL))
        silver.write.mode("overwrite").parquet(f"file://{out_dir}/silver")
        rows = spark.read.parquet(f"file://{out_dir}/silver").count()
        return {"pipeline_seconds": time.perf_counter() - started, "rows": rows}
    finally:
        spark.stop()


ENGINES = {"pandas": run_pandas, "spark": run_spark}


# --- measuring a child process ------------------------------------------------------------


def tree_rss_bytes(root_pid: int) -> int:
    """Resident memory of `root_pid` and every descendant, in bytes.

    `ps` reports RSS in kilobytes. The whole tree matters because PySpark's real work - and
    almost all of its memory - lives in a JVM child of the Python process.
    """
    try:
        output = subprocess.run(  # noqa: S603 - a fixed, absolute command, no user input
            ["/bin/ps", "-eo", "pid=,ppid=,rss="],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return 0
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        pid, ppid, kilobytes = (int(part) for part in parts)
        children.setdefault(ppid, []).append(pid)
        rss[pid] = kilobytes * 1024
    total, stack = 0, [root_pid]
    while stack:
        pid = stack.pop()
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, ()))
    return total


def measure(engine: str, env_file: str | None) -> dict:
    """Run one engine in a child process, sampling the tree's memory while it works."""
    with tempfile.TemporaryDirectory(prefix=f"bench-{engine}-") as out_dir:
        command = [sys.executable, "-m", "drugwatch_spark.benchmark", "--child", engine, out_dir]
        started = time.perf_counter()
        # noqa: S603 - the command is this interpreter running this module, not user input
        process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)  # noqa: S603
        peak = 0
        stop = threading.Event()

        def sample() -> None:
            nonlocal peak
            while not stop.is_set():
                peak = max(peak, tree_rss_bytes(process.pid))
                stop.wait(SAMPLE_SECONDS)

        watcher = threading.Thread(target=sample, daemon=True)
        watcher.start()
        stdout, _ = process.communicate()
        stop.set()
        watcher.join(timeout=1)
        total_seconds = time.perf_counter() - started

        if process.returncode != 0:
            raise RuntimeError(f"{engine} run failed:\n{stdout}")
        result = json.loads(stdout.strip().splitlines()[-1])
        return {
            **result,
            "engine": engine,
            "total_seconds": total_seconds,
            "peak_mb": peak / 1_048_576,
        }


def summarise(runs: list[dict]) -> dict:
    """The median of repeated runs, so one slow first run does not set the figure."""
    return {
        "engine": runs[0]["engine"],
        "rows": runs[0]["rows"],
        "pipeline_seconds": statistics.median(r["pipeline_seconds"] for r in runs),
        "total_seconds": statistics.median(r["total_seconds"] for r in runs),
        "peak_mb": statistics.median(r["peak_mb"] for r in runs),
    }


def table(results: list[dict]) -> str:
    """The results as a Markdown table, ready for docs/benchmarks.md."""
    lines = [
        "| Engine | Rows | Pipeline | Total (incl. start-up) | Peak memory |",
        "|---|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| {result['engine']} | {result['rows']:,} | {result['pipeline_seconds']:.1f} s "
            f"| {result['total_seconds']:.1f} s | {result['peak_mb']:,.0f} MB |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="PySpark vs pandas on the same cleaning job.")
    parser.add_argument("--child", nargs=2, metavar=("ENGINE", "OUT_DIR"), help=argparse.SUPPRESS)
    parser.add_argument("--engine", choices=sorted(ENGINES), help="measure only this engine")
    parser.add_argument("--repeat", type=int, default=1, help="runs per engine (median is kept)")
    args = parser.parse_args()

    if args.child:  # running inside the child: do the work, print one JSON line
        engine, out_dir = args.child
        print(json.dumps(ENGINES[engine](out_dir)))
        return

    engines = [args.engine] if args.engine else ["pandas", "spark"]
    results = []
    for engine in engines:
        runs = []
        for attempt in range(1, args.repeat + 1):
            print(f"{engine}: run {attempt}/{args.repeat}...", flush=True)
            runs.append(measure(engine, None))
            last = runs[-1]
            print(
                f"  {last['rows']:,} rows | pipeline {last['pipeline_seconds']:.1f} s"
                f" | total {last['total_seconds']:.1f} s | peak {last['peak_mb']:,.0f} MB",
                flush=True,
            )
        results.append(summarise(runs))

    print(f"\n{table(results)}")
    if len(results) == 2:
        slow, fast = sorted(results, key=lambda r: r["total_seconds"], reverse=True)
        print(
            f"\n{fast['engine']} is {slow['total_seconds'] / fast['total_seconds']:.0f}x faster"
            f" and uses {slow['peak_mb'] / fast['peak_mb']:.0f}x less memory at this size"
            f" ({results[0]['rows']:,} rows)."
        )


if __name__ == "__main__":
    main()
