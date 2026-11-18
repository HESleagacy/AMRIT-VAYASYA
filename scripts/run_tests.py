"""Run service suites in isolated processes without live services or credentials."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SERVICES = ('docs-mcp', 'cross-repo', 'jira-mcp')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=SERVICES, action='append')
    parser.add_argument('pytest_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    pytest_args = args.pytest_args
    if pytest_args[:1] == ['--']:
        pytest_args = pytest_args[1:]
    root = Path(__file__).resolve().parents[1]
    failed = []
    for service in args.service or SERVICES:
        with tempfile.TemporaryDirectory(prefix=f'vayasya-{service}-') as data_dir:
            env = os.environ.copy()
            env.update(
                LOCAL_DATA_DIR=data_dir,
                QDRANT_URL='http://localhost:6333',
                REDIS_URL='redis://localhost:6381/0',
                JIRA_SERVER='',
                JIRA_EMAIL='',
                JIRA_API_TOKEN='',
                HF_HUB_OFFLINE='1',
                TRANSFORMERS_OFFLINE='1',
            )
            print(f'\nRunning {service}', flush=True)
            result = subprocess.run(
                [sys.executable, '-m', 'pytest',
                 '-o', 'asyncio_default_fixture_loop_scope=function',
                 *(pytest_args or ['tests/', '-q'])],
                cwd=root / service, env=env, check=False,
            )
            if result.returncode:
                failed.append(service)
    if failed:
        print(f'\nFailed suites: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('\nAll service suites passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
