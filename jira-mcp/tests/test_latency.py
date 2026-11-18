from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from latency import Latency


def test_latency_labels_use_route_template_and_record_failures():
    app, timing = FastAPI(), Latency('test')
    timing.install(app)

    @app.get('/items/{key}')
    async def item(key: str):
        return {'ok': True}

    client = TestClient(app)
    response = client.get('/items/private-value')
    assert response.headers['Server-Timing'].startswith('app;dur=')
    assert len(response.headers['X-Request-ID']) == 32
    client.get('/does-not-exist')
    metrics = client.get('/metrics').text
    assert 'route="/items/{key}"' in metrics
    assert 'route="__unmatched__"' in metrics
    assert 'private-value' not in metrics
    with pytest.raises(ValueError):
        with timing.measure('test.failure'):
            raise ValueError('failure')
    assert timing.registry.get_sample_value(
        'vayasya_stage_duration_seconds_count',
        {'service': 'test', 'stage': 'test.failure', 'outcome': 'error'},
    ) == 1
