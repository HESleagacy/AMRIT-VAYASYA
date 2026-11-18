"""Record a sequential HTTP baseline. This tool never sends concurrent requests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
import math
from pathlib import Path
import platform
import subprocess
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def measure(url, body, timeout):
    started = perf_counter()
    status, response_hash, server_ms, error, request_id = 0, None, None, None, None
    try:
        request = Request(
            url, data=body, method='POST' if body is not None else 'GET',
            headers={'Content-Type': 'application/json'} if body is not None else {},
        )
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            response_hash = hashlib.sha256(response.read()).hexdigest()
            request_id = response.headers.get('X-Request-ID')
            timing = response.headers.get('Server-Timing', '')
            if timing.startswith('app;dur='):
                try:
                    server_ms = float(timing.removeprefix('app;dur='))
                except ValueError:
                    pass
    except HTTPError as exc:
        status, error = exc.code, 'HTTPError'
        exc.close()
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        error = type(exc).__name__
    return {
        'elapsed_ms': (perf_counter() - started) * 1000,
        'server_ms': server_ms, 'status': status, 'error': error,
        'response_sha256': response_hash, 'request_id': request_id,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--body-file', type=Path, help='JSON body; switches method to POST')
    parser.add_argument('--requests', type=int, default=50)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--label', default='sequential-baseline')
    parser.add_argument('--dataset-tag', required=True, help='Repository commits/corpus identifier')
    parser.add_argument('--cache-state', required=True, choices=['cold', 'warm', 'disabled', 'mixed'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    target = urlsplit(args.url)
    if target.scheme not in {'http', 'https'} or target.username or target.password:
        parser.error('Use an http(s) URL without embedded credentials')
    if args.requests < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error('requests/timeout must be positive and warmup non-negative')
    body = args.body_file.read_bytes() if args.body_file else None
    if body is not None:
        json.loads(body)
    warmup = [measure(args.url, body, args.timeout) for _ in range(args.warmup)]
    started = perf_counter()
    samples = [measure(args.url, body, args.timeout) for _ in range(args.requests)]
    elapsed = perf_counter() - started
    successful = [sample['elapsed_ms'] for sample in samples if 200 <= sample['status'] < 300]
    failures = len(samples) - len(successful)
    root = Path(__file__).resolve().parents[1]

    def git(*arguments):
        result = subprocess.run(
            ['git', *arguments], cwd=root, capture_output=True, text=True, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    report = {
        'schema_version': 1, 'label': args.label,
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'execution': 'sequential', 'request_concurrency': 1,
        'endpoint': urlunsplit(target._replace(query='', fragment='')),
        'query_sha256': hashlib.sha256(target.query.encode()).hexdigest(),
        'body_sha256': hashlib.sha256(body).hexdigest() if body is not None else None,
        'method': 'POST' if body is not None else 'GET',
        'dataset_tag': args.dataset_tag, 'cache_state': args.cache_state,
        'python': platform.python_version(), 'platform': platform.platform(),
        'git_revision': git('rev-parse', 'HEAD'),
        'git_dirty': bool(git('status', '--porcelain')),
        'warmup_samples': warmup,
        'summary': {
            'requests': len(samples), 'failures': failures,
            'successful_requests_per_second': len(successful) / elapsed if elapsed else 0,
            'measurement_elapsed_seconds': elapsed,
            'successful_latency_ms': {
                'p50': percentile(successful, .5), 'p95': percentile(successful, .95),
                'p99': percentile(successful, .99),
                'mean': sum(successful) / len(successful) if successful else None,
                'min': min(successful) if successful else None,
                'max': max(successful) if successful else None,
            },
        },
        'samples': samples,
    }
    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + '\n', encoding='utf-8')
        print(f'Wrote {args.output}')
    else:
        print(serialized)
    return int(failures > 0 or any(not 200 <= sample['status'] < 300 for sample in warmup))


if __name__ == '__main__':
    raise SystemExit(main())
