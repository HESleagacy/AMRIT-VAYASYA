# Versioned graph storage

Graph storage now uses `VayasyaRepo`, `VayasyaFile`, `VayasyaClass`,
`VayasyaEndpoint`, `VayasyaHttpCall`, and `VayasyaUnresolved` labels.
Logical IDs are JSON tuples including repository identity, rather than
ambiguous delimiter-joined strings. Storage identity is `(build_id, id)`.

## First rebuild and legacy data

After ingestion, call `POST /build-graph`. The first successful rebuild
publishes the new graph. Until then, new API reads return an empty graph;
they do **not** silently fall back to legacy nodes.

Legacy `Repo`/`File`/`Class`/`Endpoint` nodes and their constraints are untouched.
Old Neo4j Browser examples targeting those labels show legacy data, not the
current snapshot. No database reset, constraint drop, or destructive migration
is required. Back up important graph data before deploying schema changes.

Inspect the active graph in Neo4j Browser:

```cypher
MATCH (s:VayasyaGraphState {key: 'main'})
MATCH (e:VayasyaEndpoint {build_id: s.build_id})
RETURN e.repo, e.method, e.path
```

`GRAPH_NAMESPACE` selects the active pointer (default `main`).

## Publication and failure behavior

- Each build writes a fresh generation in **one Neo4j transaction**.
- A namespace-specific state-node write serializes rebuilds. This is a
  correctness guard, not a parallel-build optimization.
- Readers see the previous committed snapshot until all entities and links
  are ready and the active pointer commits.
- Failures roll back the entire new generation, including the pointer.
- Deleted Qdrant chunks cannot leave stale results in the next active graph:
  reads are restricted to the newly published generation.
- Previous generations are retained for inspection; they are not query-visible
  through the API. Disk-space reclamation/retention is not automated.
- Missing injected classes become context-scoped unresolved nodes. Known
  external-service name patterns are explicitly heuristic; other unresolved
  classes are classified as `missing_repo`.

The Qdrant corpus must remain stable while building: a multi-page scroll is not
a source-side snapshot. Do not ingest/reindex concurrently with a rebuild.
The graph transaction cannot make Qdrant updates atomic.

`GRAPH_BUILD_TIMEOUT_SECONDS` defaults to 300. Large corpora must fit Neo4j's
transaction memory/timeout limits; chunked publication needs a separate design.
No Python concurrency was introduced in this change.
