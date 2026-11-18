# Repository guidance

## Boundaries and invariants
- Three independently run Python services: `docs-mcp` ingests into Qdrant; `cross-repo` reads that collection into Neo4j; `jira-mcp` calls cross-repo's `/explain` over HTTP. Do not add cross-service Python imports.
- Run commands from the relevant service directory, not the repository root. Services use colliding top-level names (`core`, `config`, `api`, `tests`), and settings load `.env` relative to the working directory. Run test suites in separate processes.
- `docs-mcp/data/` contains ignored ingestion state and cloned external repositories, not Vayasya packages. Exclude it from architecture/config searches; its Java/Angular manifests and CI belong to the ingested projects.
- Graph traversal and evidence collection remain deterministic; Groq only narrates assembled evidence. `cross-repo/core/evidence.py` defines the evidence contract consumed by API, MCP, CLI, and Jira planning.
- Preserve repository, file, line, and structural metadata through parsing/chunking. `docs-mcp/core/models.py` payloads feed `cross-repo/core/graph_builder.py` (`classes`, `api_routes`, `http_calls`, `dependencies`).

## Setup and execution
- Use Python 3.11+ (`docs-mcp/pyproject.toml` and Dockerfile), despite README references to 3.10.
- Commands below use `python` for the selected environment's interpreter; use `python3` on macOS/Linux or `py -3.11` on Windows if needed. Use `python -m ...` to avoid relying on executable PATH setup.
- In each service, install with `python -m pip install -r requirements.txt`; cross-repo also needs `python -m pip install pytest` for tests.
- Create a missing service `.env` from its `.env.example`; do not overwrite an existing local environment.
- From `docs-mcp`, `docker compose up -d --build` starts the docs API, worker, Qdrant, Redis, and Neo4j—not cross-repo or Jira.
- Local API commands, from their respective service directories:
  - docs: `python -m uvicorn apps.api.main:app --port 8000 --reload`
  - cross-repo: `python -m uvicorn api:app --port 8001 --reload`
  - Jira: `python -m uvicorn api:app --port 8002 --reload`
- `docs-mcp/.env.example` targets Docker networking (`qdrant`, `redis`, `/data`). For host-run docs commands/tests, override `QDRANT_URL=http://localhost:6333`, `REDIS_URL=redis://localhost:6381/0`, and `LOCAL_DATA_DIR=./data`. Redis is exposed on **6381**, not 6379.
- Put persistent overrides in the service `.env`, not shell-specific `VAR=value command` syntax. `/data` is a container path, not a host setup requirement. Docker Compose requires Linux-container support (Docker Desktop on Windows/macOS).
- Collection env names differ: docs uses `DOCS_MCP_COLLECTION`; cross-repo uses `COLLECTION_NAME`. They must point to the same Qdrant collection (default `docs_chunks`).
- End-to-end order: start infrastructure → ingest via docs `POST /ingest` → start cross-repo → `POST http://localhost:8001/build-graph` → trace/explain or generate Jira plans. Portable graph-build command: `python -c "import urllib.request; print(urllib.request.urlopen(urllib.request.Request('http://localhost:8001/build-graph', method='POST')).read().decode())"` (avoids PowerShell's `curl` alias).
- Docs `POST /ingest` awaits ingestion synchronously; progress is `GET /ingest/{job_id}`, not the README's `/progress/{repo_name}`.
- From `cross-repo`, `python skills/api_flow_explainer.py "patient" --mode deterministic --json` exercises evidence collection without Groq, but still needs Neo4j/Qdrant. `--mode explain` additionally needs `GROQ_API_KEY`.

## Focused verification
From the repository root, install lightweight test dependencies with `python -m pip install -r requirements-test.txt`, then run `python scripts/run_tests.py`. This isolates service processes and temporary ingestion data; see `TESTING.md`. Focus a suite with `--service cross-repo`, or append `-- tests/test_route_normalizer.py -q` for a file.

Run from each service directory:

| Service | Command |
| --- | --- |
| docs-mcp | `python -m pytest tests/ -q` |
| cross-repo | `python -m pytest tests/ -v` |
| jira-mcp (offline/mock) | `python -c "import os, pytest; os.environ.update(JIRA_SERVER='', JIRA_EMAIL='', JIRA_API_TOKEN=''); raise SystemExit(pytest.main(['tests/', '-v']))"` |

- Single-test example from `cross-repo`: `python -m pytest tests/test_route_normalizer.py::TestNormalizeRoute::test_spring_template_normalised -v`.
- Jira client tests blank local credentials and mock SDK calls; they never intentionally use live Jira. The application still switches to live Jira when all three credentials are configured.
- Keep `tree-sitter` below 0.22 while using `tree-sitter-languages` 1.10.x; newer parser APIs otherwise silently force regex fallback.
- Active graph reads use versioned `Vayasya*` labels, not legacy `File`/`Class`/`Endpoint` labels. A successful `POST /build-graph` publishes a fresh snapshot atomically; no legacy nodes are deleted. See `cross-repo/GRAPH_STORAGE.md`.
- BM25 source chunks persist in collection-scoped SQLite under `LOCAL_DATA_DIR`; API/worker must share that directory. For pre-existing Qdrant data, run `python -m scripts.rebuild_keyword_index` from `docs-mcp` while ingestion is paused.
- Concurrency optimization is deferred. `/metrics` and `scripts/record_latency.py` provide sequential baseline timing; see `LATENCY.md`. Keep cache/model/dataset conditions explicit when comparing results.
- Docs API import constructs `IngestionService` and creates `LOCAL_DATA_DIR` before test monkeypatches run; use a writable local path rather than the Docker `/data` value.
- Ruff configuration exists only in `docs-mcp/pyproject.toml` (line length 100); from `docs-mcp`, run `python -m ruff check .` after installing Ruff separately. No repository-wide lint/typecheck pipeline is configured.

## Contribution convention
- `CONTRIBUTING.md` requests plain-English commit messages without conventional-commit prefixes.
