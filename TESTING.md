# Offline verification

Use Python 3.11 or 3.12. From the repository root:

```text
python -m pip install -r requirements-test.txt
python scripts/run_tests.py
```

The runner uses the current interpreter, runs each service in its own process
and working directory, isolates ingestion data in temporary directories, blanks
Jira credentials, and disables Hugging Face downloads. No Docker, API keys,
Neo4j server, Redis server, or Qdrant server is needed. Vector-store tests use
Qdrant's in-memory mode; Jira SDK and HTTP calls are mocked.

Run one suite or forward a pytest selection after `--`:

```text
python scripts/run_tests.py --service cross-repo
python scripts/run_tests.py --service cross-repo -- tests/test_route_normalizer.py -q
```

These commands work in POSIX shells, PowerShell, and cmd.exe. Substitute `python3`
or `py -3.11` if that selects your environment's interpreter. Do not run all three
service test directories in one pytest process: their imports overlap.

CI runs this suite on Linux, macOS, and Windows with Python 3.11 and 3.12.
This is offline verification, not a live integration or deployment check.
ML model inference, MCP transports, Docker startup, and live graph/Jira behavior
still require separate integration verification.

## Graph integration

`cross-repo/integration/` is separate from the offline suites and requires a
**disposable** Neo4j 5.18+ instance. Set `VAYASYA_TEST_NEO4J_URI`,
`VAYASYA_TEST_NEO4J_USER` (default `neo4j`), and
`VAYASYA_TEST_NEO4J_PASSWORD` (default `test-password`) in your shell, then:

```text
cd cross-repo
python -m pytest integration/ -q
```

These tests create schema constraints and random test namespaces, then delete
only their own test entities/state. Do not point them at a production database.
The separate graph-integration CI job provisions Neo4j automatically.
