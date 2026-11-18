import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from config import Settings
from integrations import plan_generator


def test_explain_uses_dotenv_settings_and_encodes_feature(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('CROSS_REPO_URL=http://graph.example.test:9001/\n', encoding='utf-8')
    monkeypatch.delenv('CROSS_REPO_URL', raising=False)
    settings = Settings(_env_file=env)
    monkeypatch.setattr(plan_generator, 'get_settings', lambda: settings)
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        assert timeout == 15
        return io.BytesIO(json.dumps({'feature': 'patient'}).encode())

    monkeypatch.setattr(plan_generator.urllib.request, 'urlopen', urlopen)
    assert plan_generator._call_cross_repo_explain('patient/a & b') == {'feature': 'patient'}
    url = urlsplit(requests[0].full_url)
    assert url.netloc == 'graph.example.test:9001'
    assert url.path == '/explain'
    assert parse_qs(url.query) == {'feature': ['patient/a & b']}


@pytest.mark.parametrize('error', [
    HTTPError('http://example.test', 404, 'not found', {}, None),
    URLError('offline'),
])
def test_explain_distinguishes_missing_evidence_from_unavailable_service(monkeypatch, error):
    def urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr(plan_generator.urllib.request, 'urlopen', urlopen)
    if isinstance(error, HTTPError):
        assert plan_generator._call_cross_repo_explain('patient') is None
    else:
        with pytest.raises(RuntimeError, match='Could not reach'):
            plan_generator._call_cross_repo_explain('patient')


def test_suggested_files_preserve_identical_paths_in_different_repositories():
    ticket = {'key': 'TEST-1', 'summary': 'Patient change'}
    evidence = {'backend_endpoints': [
        {
            'repo': repo, 'backend_file': 'src/Controller.java', 'method': 'GET',
            'path': '/patient', 'handler_class': 'Controller', 'handler_kind': 'controller',
        }
        for repo in ('a', 'b', 'a')
    ]}
    plan = plan_generator._render_plan(ticket, evidence)
    assert plan.count('[a]  src/Controller.java') == 1
    assert plan.count('[b]  src/Controller.java') == 1
