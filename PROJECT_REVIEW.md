# Project hardening report

## Verification

- Baseline: 46 passed, 2 live-Jira tests skipped.
- After the first hardening pass: 83 passed, no skips.
- After the priority follow-up: **104 offline tests passed, no skips**
  (docs 36, cross-repo 52, Jira 16), plus **4 real Neo4j integration tests**.
- Verified on macOS ARM64 in clean Python 3.11 and 3.12 environments using
  only `requirements-test.txt`. Graph integration was separately verified
  against a disposable native Neo4j 5.18 server; that server was stopped afterward.
- Portable command: `python scripts/run_tests.py`; see `TESTING.md`.
- Basic static checks pass:
  `python -m ruff check --isolated --select F,E9 cross-repo jira-mcp docs-mcp/apps docs-mcp/core docs-mcp/tests docs-mcp/scripts scripts`.
- Added a Linux/macOS/Windows CI matrix for Python 3.11 and 3.12. Remote CI
  has not been executed in this session.
- No deployed services, existing graph data, live Jira, or ingested repository
  data were modified. The pre-existing root README changes were preserved.

## Fixed

- Route matching no longer equates missing routes or mistakes `/patient` for
  `/patients`. Root routes, leading-slash-free IDs, URL fragments, and
  JavaScript `${id}` templates normalize correctly.
- Evidence collection retains service-chain branches across duplicate trace
  rows, preserves original path-parameter names, deduplicates callers, and
  scopes supporting code/DTO lookup by repository.
- Trace queries now include the caller's actual HTTP path rather than silently
  substituting the backend route.
- Graph dependency linking occurs after all Qdrant pages are ingested, avoiding
  missing edges when the referenced class appears later.
- Graph builder and evidence collector close both database clients.
- Jira planning honors `.env` through the settings model, encodes query
  parameters safely, and preserves same-path files from different repositories.
- Jira publish errors retain their actionable message.
- Qdrant initialization is lazy. Search supports the current query API, older
  clients, and the Compose-pinned 1.9 server's REST search endpoint. Server
  errors are not silently converted to empty results.
- Tree-sitter dependencies are constrained to compatible APIs; Unicode source
  extraction uses byte offsets correctly.
- Ingestion rejects clone-directory traversal, validates local directories,
  excludes escaped symlink targets, and applies ignored-directory rules
  relative to the ingested root. Relative metadata paths use `/` across OSes.
- Long prose is split to the configured chunk token limit, zero overlap is
  honored, and rebalancing cannot exceed that limit. Code fences intentionally
  remain atomic even when oversized.
- Chunking works without pre-enriched timestamps; generated model timestamps
  use timezone-aware UTC rather than deprecated `utcnow()`.

## Test cleanup

- Removed two duplicate Jira core tests and two environment-dependent live
  Jira tests. Mocked SDK tests now exercise listing, fallback, publishing,
  and publishing failures without contacting an account.
- Added focused regressions for the fixes above, in-memory Qdrant coverage,
  a lightweight test dependency manifest, and an isolated service test runner.
- Removed unused imports, an unused exception binding, and redundant f-string
  prefixes; avoided a repository-wide style rewrite.

## Priority follow-up

- **Graph identity collisions:** new versioned `Vayasya*` graph labels use
  repository-scoped JSON tuple identities and `(build_id, id)` constraints.
  Legacy labels/constraints are preserved, not destructively migrated.
- **Stale rebuild results:** a complete generation and its active pointer
  publish in one transaction. Reads only use the active generation; failed
  builds roll back. Inactive generations remain on disk for inspection.
- **Unresolved dependencies:** graph construction records missing injected
  classes and external-service-pattern matches with source context; evidence
  collection consumes those graph edges rather than comparing resolved names
  against themselves.
- **Keyword persistence:** a transactional SQLite source corpus is shared by
  API/worker processes on the same filesystem. Scorers refresh on revision
  changes. Query cache keys include corpus revision, collection, and model
  configuration. A recovery command hydrates pre-existing Qdrant datasets.
- **Standards loading:** Spring annotation/naming patterns and Angular naming
  patterns now load from YAML, with built-in fallback for absent files.
- **Latency baseline:** all three APIs expose Prometheus histograms,
  `Server-Timing`, request IDs, and structured request timing logs. Sequential
  pipeline stages are measured without rearranging execution.
- `scripts/record_latency.py` records sequential full-response samples,
  p50/p95/p99, failures, throughput, environment metadata, and response digests.
  **Concurrency and speedup comparisons are explicitly deferred.**

Operational notes: `cross-repo/GRAPH_STORAGE.md`,
`docs-mcp/docs/keyword_index.md`, and `LATENCY.md`.

## Remaining limits and follow-ups

These are not claims of production readiness:

1. **Stable source required during rebuild/recovery.** Qdrant pagination is
   not an immutable source snapshot. Pause ingestion while rebuilding graphs
   or recovering the keyword corpus.
2. **Graph retention/capacity.** Inactive generations are not query-visible,
   but need an explicit disk-retention policy. Large builds must fit the
   single-transaction memory and timeout budgets.
3. **Standards validation.** `allowed_dependencies` is documented but not yet
   enforced. Classification loading is implemented; layering validation is not.
4. **Deployment boundaries.** SQLite sharing requires a local shared volume,
   not independent replica disks or an assumed network-filesystem guarantee.
   Mount YAML standards explicitly in standalone cross-repo containers.
5. **Observability scope.** Metrics are process-local; multi-worker aggregation
   is not configured. No real-dataset latency baseline or concurrency comparison
   has been captured, and no latency-reduction claim has been made.

Live Qdrant/server-version integration, real ML inference, MCP transport, and
Docker startup still need end-to-end verification. Upstream Starlette/httpx
and Tree-sitter deprecation warnings remain. Full style lint/type checking
was not made a release gate in this pass.
