# Benchmarks

## 1. Pandas vs PySpark on the Phase 3 cleaning job (2026-11-16)

Phase 3 step 9. The question the plan asks is simple: the cleaning pipeline that turns bronze into silver is
written in PySpark — what would the same job cost in pandas?

### What was measured

**The same job, proven.** `pandas_pipeline.py` is a pandas implementation of `build_silver.py`. It is not a
parallel reimplementation: it **imports the same logic** — the pure Python functions the Spark job wraps in UDFs
(`split_combined_cell`, `strengths_in`, `split_brand_generic`, `clean_manufacturer_name`, `cluster_variants`), the
same regex constants (`dosage_form.PATTERNS`, `failure_category.CATEGORIES`) and the same column list
(`build_silver.SILVER_COLUMNS`). Only what Spark expressed as `Column` operations had to be written twice:
whitespace cleaning, date parsing, the schema mapping and de-duplication.

`compare_engines.py` then checks the two outputs match:

```
spark silver : 7128 rows
pandas silver: 7128 rows
identical: 7128 rows x 32 columns agree exactly
```

So this measures the cost of the same work, not of two different jobs.

**The work:** read both bronze datasets from RustFS (1,317 PDF rows + 7,005 portal rows), run every Phase 3
cleaning step (whitespace, dates, dosage form, strengths, brand/generic split, manufacturer name and address,
RapidFuzz clustering across both sources, failure categories, de-duplication) and write the 7,128-row silver
table as Parquet.

**How it was measured** (`benchmark.py`, median of 3 runs each):

- **Each engine runs in its own subprocess.** Spark's work happens in a JVM the Python process cannot see, and
  one engine's heap would pollute the other's figure in a shared process.
- **Peak memory is sampled across the whole process tree** (Python driver *and* its JVM child) every 100 ms,
  taking the maximum. `resource.getrusage` only reports children that have been waited for, which misses a
  running JVM.
- **Two times are reported.** *Pipeline* is the work itself; *total* adds interpreter and JVM start-up and jar
  resolution. Start-up is a real cost that a monthly Airflow task pays on every run, so hiding it would flatter
  Spark.
- **Both write silver to a local temp directory**, which forces each engine to actually materialise every row —
  a lazy engine could otherwise "finish" without doing the work — while keeping object-store write behaviour out
  of the comparison. Reads come from RustFS in both cases (Spark over Hadoop S3A, pandas over pyarrow).

**Machine:** Apple M2, 8 cores, 8 GB RAM, macOS 26.5.1, Python 3.13.5, PySpark 4.2.1 on OpenJDK 21,
pandas 2.3.3, pyarrow 26.0.1. RustFS ran in Docker on the same machine. pandas is single-threaded.

**Spark ran with this project's tuned settings** (`session.py`), not stock defaults — and the tuning was itself
forced by this benchmark, since the first attempts either crashed or took minutes:

| Setting | Why |
|---|---|
| `local[4]`, not `local[*]` | Every task slot running a Python UDF starts its own Python worker. 8 slots meant ~13 workers and a 3.2 GB peak, which pushed an 8 GB Mac into swap — and one run died with *"Python worker exited unexpectedly"*. At a few thousand rows the lost parallelism costs nothing. |
| `spark.driver.memory = 2g` | In local mode the executor **is** the driver JVM, so this is the whole Spark heap (`spark.executor.memory` is ignored). Left at the 1 GB default the JVM spent its time in GC. |
| `spark.driver.bindAddress/host = 127.0.0.1` | Spark derives its RPC address from the hostname. On a Mac with Internet Sharing configured that resolved to the **inactive** `bridge0` interface, and every driver↔executor message waited out a 10 s timeout: a ~15 s job took **9 minutes at 22% CPU**. One JVM on one machine should talk over loopback. |
| `fs.s3a.input.stream.type = classic` | Hadoop 3.5.0 defaults to the analytics-accelerator reader, tuned for large objects on real S3. Against local RustFS it stalled — a 31 KB read took 39.5 s, others hit the 60 s timeout — while pyarrow read the same objects in 0.02 s. |

Those four settings are why Spark's figure below is ~2 minutes rather than ~10. **A stock-default PySpark on this
hardware performs far worse than the table shows**, which is worth stating plainly: most of the gap between
"Spark is slow here" and "Spark is unusable here" was configuration, and finding it took longer than writing
either pipeline.

### Results

| Engine | Rows | Pipeline | Total (incl. start-up) | Peak memory |
|---|---:|---:|---:|---:|
| **pandas** | 7,128 | **6.1 s** | **6.5 s** | **181 MB** |
| PySpark | 7,128 | 111.4 s | 124.1 s | 2,723 MB |

Per run, to show the spread:

| Engine | Pipeline (3 runs) | Total (3 runs) | Peak memory (3 runs) |
|---|---|---|---|
| pandas | 6.4 / 6.1 / 6.0 s | 7.2 / 6.5 / 6.5 s | 149 / 181 / 184 MB |
| PySpark | 64.8 / 113.6 / 111.4 s | 77.1 / 131.6 / 124.1 s | 2,319 / 2,782 / 2,723 MB |

*Row count: measured on the 7,128-row silver table of 2026-11-16. Harith's manufacturer review (195 accepted merges, 2026-11-18) later revealed two duplicate findings, so silver now holds 7,126 rows. The timings were not re-run: two rows in 7,128 cannot move them, and `compare_engines.py` still reports both engines identical at 7,126.*

**At this size pandas is roughly 19x faster and uses about 15x less memory.**

**Spark's figure is unstable on this machine and should be read as a range, not a point.** Across two sessions
its total ranged from 56 s to 132 s for identical work, while pandas stayed within 0.7 s of its median every
time. On an 8 GB laptop Spark is competing with Docker and the OS for memory, and its own variance is larger
than pandas' entire runtime. That instability is itself a finding: it is the behaviour of a tool being run far
outside the conditions it was designed for.

### Why, and what it does not mean

- **The archive is tiny.** 8,322 input rows is kilobytes of data. Spark's design — partitioning, shuffling,
  scheduling tasks across executors — is overhead you pay per job and only earn back when the data does not fit
  on one machine. Here it never pays off.
- **Start-up is ~10 s of Spark's time** before any row is read: JVM launch plus resolving the S3A connector jars.
- **This pipeline is UDF-heavy, which is the honest caveat.** Most cleaning steps are Python functions
  (`clean_manufacturer_name`, `strengths_in`, …) running as UDFs, so Spark serialises every row out to a Python
  worker and back, losing the advantage of its JVM engine. **A Spark-native rewrite using only built-in SQL
  expressions would close much of this gap** — this is a fair measurement of *this* pipeline, not a general claim
  that pandas beats Spark.
- **Memory is where the gap is structural, not incidental.** 2.7 GB against 181 MB on a job with kilobytes of
  input is the JVM heap, 8 task threads and 8 Python worker processes, not the data.
- **Observed on this machine:** with `local[*]` one run died outright with *"Python worker exited unexpectedly
  (crashed)"* — 8 Python workers alongside Docker's VM on an 8 GB laptop. That is what prompted the `local[4]`
  setting above. pandas never came close to that limit, at 181 MB. For a single-machine deployment that is a
  real operational difference, not a theoretical one.

### Why the project still uses PySpark

Phase 3 is built on PySpark deliberately, and this benchmark does not overturn that:

1. **It is a learning and portfolio project** (CLAUDE.md §2). Knowing why Spark is the wrong tool at 7,000 rows —
   with measurements — is worth more than never having used it.
2. **The architecture is the point.** The same job runs unchanged on a cluster if the data grows; CDSCO publishes
   monthly, so silver grows by roughly 100–300 rows a month.
3. **Where the crossover would be:** on this hardware the gap is memory, not CPU. pandas holds the whole table in
   one process, so it stops working when silver no longer fits in RAM — at ~181 MB for 7,128 rows, mostly Python
   object overhead, that is still millions of rows away. The honest conclusion is that **pandas would serve this
   project's current data comfortably**, and Spark is carried for the architecture and the learning, not for
   present performance.

### The benchmark improved the code it was measuring

The first pandas implementation filled each group's gaps with `transform(lambda col: col.ffill().bfill())`.
Measuring it made the cost visible, and replacing it with `GroupBy.first()` — which *is* "the first non-null
value per column", the same thing Spark's `first(ignorenulls=True)` over an ordered window does — **halved the
runtime (12.3 s → 6.1 s) and cut peak memory by 2.3x (423 MB → 181 MB)**, with `compare_engines.py` confirming
the output stayed identical. `transform` re-walked every group once per column and leaned on object-dtype
downcasting that pandas has since deprecated.

The lesson is worth keeping: the first number a benchmark produces usually measures the implementation, not the
tool. The Spark side almost certainly has similar headroom — see the UDF caveat above.

### One incidental finding

`build_silver.main()` takes around 10 minutes against the ~2 minutes measured here, on the same work. The difference is
its report: each `count()` and fill-rate figure re-evaluates the pipeline, and the UDF chain is re-run every time.
Worth knowing before trusting a wall-clock number taken from a job that also prints a report — and a hint that
`main()` should cache more aggressively if it is ever run on a schedule.

### Reproducing

```bash
cd spark
uv run --env-file ../.env python -m drugwatch_spark.compare_engines   # prove both engines agree
uv run --env-file ../.env python -m drugwatch_spark.benchmark --repeat 3
```
