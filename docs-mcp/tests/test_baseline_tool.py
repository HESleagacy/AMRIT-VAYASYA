import importlib.util
import json
from pathlib import Path
import sys
import io
from urllib.error import URLError


def load_tool():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'record_latency.py'
    spec = importlib.util.spec_from_file_location('record_latency', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_statistics_and_failures_are_reported_without_filtering_samples(tmp_path, monkeypatch):
    tool = load_tool()
    output = tmp_path / 'baseline.json'
    samples = iter([
        {'status': 200, 'elapsed_ms': 10},
        {'status': 503, 'elapsed_ms': 30},
        {'status': 200, 'elapsed_ms': 20},
    ])
    monkeypatch.setattr(tool, 'measure', lambda *args: next(samples))
    monkeypatch.setattr(sys, 'argv', [
        'record_latency.py', '--url', 'http://localhost:8000/query?private=value',
        '--requests', '3', '--warmup', '0', '--dataset-tag', 'fixture-v1',
        '--cache-state', 'disabled', '--output', str(output),
    ])
    assert tool.main() == 1
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['summary']['failures'] == 1
    assert report['summary']['successful_latency_ms']['p50'] == 10
    assert report['summary']['successful_latency_ms']['p95'] == 20
    assert len(report['samples']) == 3
    assert report['request_concurrency'] == 1
    assert report['endpoint'] == 'http://localhost:8000/query'
    assert 'private=value' not in output.read_text(encoding='utf-8')


def test_http_measurement_reads_complete_body_and_correlates_server_timing(monkeypatch):
    tool = load_tool()
    response = io.BytesIO(b'{"ok": true}')
    response.status = 200
    response.headers = {'Server-Timing': 'app;dur=12.500', 'X-Request-ID': 'request-1'}
    monkeypatch.setattr(tool, 'urlopen', lambda *args, **kwargs: response)
    sample = tool.measure('http://localhost/test', None, 5)
    assert sample['server_ms'] == 12.5
    assert sample['request_id'] == 'request-1'
    assert sample['response_sha256'] is not None
    assert sample['elapsed_ms'] >= 0


def test_http_connection_failure_is_retained_as_a_sample(monkeypatch):
    tool = load_tool()

    def unavailable(*args, **kwargs):
        raise URLError('offline')

    monkeypatch.setattr(tool, 'urlopen', unavailable)
    sample = tool.measure('http://localhost/test', None, 5)
    assert sample['status'] == 0
    assert sample['error'] == 'URLError'
