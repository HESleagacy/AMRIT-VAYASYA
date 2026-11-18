"""Offline tests for built-in tickets and the mocked Jira SDK boundary."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import get_settings
from integrations.jira_client import get_ticket, list_tickets, post_comment, _MOCK_TICKETS


@pytest.fixture(autouse=True)
def offline_jira(monkeypatch):
    for key in ('JIRA_SERVER', 'JIRA_EMAIL', 'JIRA_API_TOKEN'):
        monkeypatch.setenv(key, '')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestMockJiraClient:
    """Validate the canonical tickets without consulting local credentials."""

    def test_list_tickets_returns_all_five(self):
        tickets = list_tickets()
        assert len(tickets) == 5
        assert all({'key', 'summary', 'status'} <= ticket.keys() for ticket in tickets)

    def test_get_existing_ticket(self):
        ticket = get_ticket('AMRIT-101')
        assert ticket['key'] == 'AMRIT-101'
        assert 'beneficiary' in ticket['summary'].lower()
        assert ticket['affected_feature'] == 'beneficiary'

    def test_get_ticket_case_insensitive(self):
        ticket = get_ticket('amrit-102')
        assert ticket['key'] == 'AMRIT-102'

    def test_get_unknown_ticket_raises(self):
        with pytest.raises(ValueError, match='not found'):
            get_ticket('AMRIT-999')

    def test_all_mock_tickets_have_affected_feature(self):
        for key, ticket in _MOCK_TICKETS.items():
            assert ticket.get('affected_feature'), f'{key} missing affected_feature'

    def test_amrit_102_is_healthid_feature(self):
        ticket = get_ticket('AMRIT-102')
        assert ticket['affected_feature'] == 'healthID'

    def test_amrit_103_is_patient_feature(self):
        ticket = get_ticket('AMRIT-103')
        assert ticket['affected_feature'] == 'patient'


@pytest.fixture
def jira_sdk(monkeypatch):
    import jira

    monkeypatch.setenv('JIRA_SERVER', 'https://jira.example.test')
    monkeypatch.setenv('JIRA_EMAIL', 'test@example.test')
    monkeypatch.setenv('JIRA_API_TOKEN', 'test-token')
    get_settings.cache_clear()
    sdk = Mock()
    monkeypatch.setattr(jira, 'JIRA', Mock(return_value=sdk))
    return sdk


def test_sdk_list_maps_issue_fields(jira_sdk):
    jira_sdk.search_issues.return_value = [
        SimpleNamespace(key='TEST-1', fields=SimpleNamespace(
            summary='Patient registration', status='Open', priority='High', issuetype='Bug',
        )),
    ]
    assert list_tickets() == [{
        'key': 'TEST-1', 'summary': 'Patient registration', 'status': 'Open',
        'priority': 'High', 'ticket_type': 'bug',
    }]


def test_sdk_failure_falls_back_to_builtin_tickets(jira_sdk):
    jira_sdk.search_issues.side_effect = RuntimeError('unavailable')
    assert len(list_tickets()) == 5


def test_publish_uses_sdk_and_reports_failure(jira_sdk):
    assert post_comment('TEST-1', 'Plan') == (True, 'Success')
    jira_sdk.add_comment.assert_called_once_with('TEST-1', 'Plan')
    jira_sdk.add_comment.side_effect = RuntimeError('permission denied')
    assert post_comment('TEST-1', 'Plan') == (False, 'permission denied')
