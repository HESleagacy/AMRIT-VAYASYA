from fastapi.testclient import TestClient

import api
from integrations import jira_client


def test_publish_preserves_actionable_error_message(monkeypatch):
    monkeypatch.setattr(api, 'generate_implementation_plan', lambda key: 'plan')
    monkeypatch.setattr(jira_client, 'post_comment', lambda *args: (False, 'permission denied'))
    response = TestClient(api.app).post('/plan/TEST-1/publish')
    assert response.status_code == 500
    assert response.json() == {'detail': 'Jira API Error: permission denied'}
