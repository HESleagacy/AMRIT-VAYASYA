"""Service-local baseline timing; independent of the other services."""
from contextlib import contextmanager
import json
import logging
from time import perf_counter
from uuid import uuid4

from prometheus_client import CollectorRegistry, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response


class Latency:
    def __init__(self, service):
        self.service = service
        self.registry = CollectorRegistry()
        buckets = (.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60, 300)
        self.requests = Histogram(
            'vayasya_http_duration_seconds', 'Time until response headers are ready',
            ('service', 'method', 'route', 'status'), buckets=buckets, registry=self.registry,
        )
        self.stages = Histogram(
            'vayasya_stage_duration_seconds', 'Sequential pipeline stage elapsed time',
            ('service', 'stage', 'outcome'), buckets=buckets, registry=self.registry,
        )

    @contextmanager
    def measure(self, stage):
        started, outcome = perf_counter(), 'ok'
        try:
            yield
        except BaseException:
            outcome = 'error'
            raise
        finally:
            self.stages.labels(self.service, stage, outcome).observe(perf_counter() - started)

    def install(self, app):
        @app.middleware('http')
        async def timing(request, call_next):
            started, status = perf_counter(), 500
            request_id = uuid4().hex
            try:
                response = await call_next(request)
                status = response.status_code
                response.headers['Server-Timing'] = f'app;dur={(perf_counter() - started) * 1000:.3f}'
                response.headers['X-Request-ID'] = request_id
                return response
            finally:
                elapsed = perf_counter() - started
                route = getattr(request.scope.get('route'), 'path', '__unmatched__')
                method = request.method if request.method in {
                    'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS',
                } else 'OTHER'
                if route != '/metrics':
                    self.requests.labels(self.service, method, route, str(status)).observe(elapsed)
                    logging.getLogger('vayasya.latency').info(json.dumps({
                        'service': self.service, 'route': route, 'method': method,
                        'status': status, 'elapsed_ms': round(elapsed * 1000, 3),
                        'request_id': request_id,
                    }))

        @app.get('/metrics', include_in_schema=False)
        def metrics():
            return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)


latency = Latency('cross-repo')
