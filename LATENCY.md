# Sequential latency baseline

**Concurrency has not been added.** These measurements establish the current
baseline for a later, separately measured concurrency implementation.

## Server measurements

Each API now exposes:

- `GET /metrics`: Prometheus histograms for HTTP and pipeline-stage latency.
- `Server-Timing: app;dur=...`: elapsed milliseconds until response headers.
- `X-Request-ID`: a generated identifier, also included in structured request
  logs when the `vayasya.latency` logger is configured at INFO.

Timing uses `perf_counter`, not wall-clock timestamps. Route labels use path
templates, never feature queries, ticket keys, or patient identifiers.
Unmatched routes use a single fixed label. Treat `/metrics` as an internal
endpoint; place it behind the same access controls as the APIs.

Instrumented stages include docs index refresh, cache lookup, embedding,
vector search, keyword search, reranking, and total retrieval; graph builds;
evidence graph/vector retrieval; Jira planning and the cross-repo HTTP call.
Stages remain in their existing sequential order.

Metrics are per-process and reset at restart. Multi-worker Prometheus
aggregation is not configured; use one API worker for baseline capture.
Server header timing excludes response-body transfer. Measure end-to-end
latency separately with the recorder below.

Example PromQL for approximate rolling HTTP p95:

```promql
histogram_quantile(
  0.95,
  sum by (le, service, route) (
    rate(vayasya_http_duration_seconds_bucket[5m])
  )
)
```

Inspect stage `_count`, `_sum`, and `_bucket` samples for bottlenecks and error
outcomes. Nested stage sums must not be interpreted as end-to-end time.

## Record raw HTTP samples

Start the required services and populate a fixed dataset first. From the
repository root:

```text
python scripts/record_latency.py --url http://localhost:8000/query --body-file benchmarks/query.json --dataset-tag corpus-commit-or-snapshot --cache-state warm --requests 100 --warmup 10 --output benchmarks/results/baseline.json
```

The recorder sends **one request at a time**, without retries. It captures:

- warmup samples separately from measured samples;
- full-response elapsed time, HTTP status, error type, response digest, and
  server header time when available;
- successful-request p50/p95/p99, mean/min/max, failures, and achieved throughput;
- dataset/cache labels, Python/platform, Git revision, dirty-tree status,
  request-body/query digests, and capture timestamp.

Failures remain in the raw samples and make the command exit nonzero. Percentiles
are nearest-rank over successful requests only, so always report failure counts
beside them. Small samples make p99 particularly unstable.

`--cache-state` describes the experiment; it does **not** flush or disable
caches. Keep cache state, corpus, model versions, hardware, request mix, API
worker count, and warmup policy identical in later comparisons. Save model
configuration and dependency versions beside results:

```text
python -m pip freeze
```

Record cold-start and warmed-model runs separately. Cached requests skipping
embedding/search are not evidence of a concurrency speedup. Python/model
fallbacks must be disclosed; hash-embedding fallback is not real ML inference.

The tool's POST target must be a read-only query endpoint. Do not benchmark
ingestion, graph rebuilding, or Jira publishing by repeatedly POSTing to them.
Request/response bodies are not stored, but avoid secrets in URLs and dataset
labels. Local output under `benchmarks/results/` is ignored by Git.

No latency-reduction claim or sequential-vs-concurrent result has been made.
