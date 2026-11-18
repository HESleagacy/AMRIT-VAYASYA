# Persistent keyword corpus

The BM25 scorer now rebuilds from source chunks stored in SQLite under
`LOCAL_DATA_DIR/bm25-<collection-hash>.sqlite3`. Creation is lazy.

API and Celery worker processes sharing the same data directory see committed
corpus revisions on their next query. The existing Compose `/data` volume is
shared by both. Each process holds its own scorer but refreshes it from the
same corpus; it does not share Python objects.

Updates/deletions and their revision increment commit atomically. Cache keys
include that revision, so ingestion in a different process invalidates previous
query responses without waiting for their TTL.

For already-ingested Qdrant data, recover the local derived corpus explicitly:

```text
cd docs-mcp
python -m scripts.rebuild_keyword_index
```

Use the same collection and data-directory settings as the API. For a
container deployment, run `docker compose exec api python -m scripts.rebuild_keyword_index`.
Only the local keyword corpus is replaced; Qdrant is read, not modified.
Retrieval/validation failures leave the old keyword corpus intact.

Pause ingestion during recovery so the Qdrant scroll and corpus replacement
refer to a stable source. Separate host/container data paths are not shared
automatically. Existing cached queries use the new corpus revision on the
next lookup.

SQLite WAL is for processes on one local filesystem; do not assume it is a
distributed index for replicas with independent disks or network filesystems.
Loading/rebuilding a scorer still costs CPU/memory proportional to corpus size.
The pipeline remains sequential; concurrency optimization is deferred.
