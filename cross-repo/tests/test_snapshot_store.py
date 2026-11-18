from unittest.mock import MagicMock

import pytest

from core.graph_identity import entity_id
from core.neo4j_client import Neo4jClient


def store():
    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = MagicMock()
    client._graph_key = 'test'
    client._build_timeout = 30
    client._transaction, client._build_id = None, None
    return client


def test_snapshot_publication_is_after_all_writes_and_failure_never_commits():
    client = store()
    transaction = client._driver.session.return_value.__enter__.return_value.begin_transaction.return_value.__enter__.return_value
    with pytest.raises(RuntimeError, match='parse failed'):
        with client.build_snapshot():
            client.upsert_repo('a')
            raise RuntimeError('parse failed')
    transaction.commit.assert_not_called()
    assert not any('published_at' in call.args[0] for call in transaction.run.call_args_list)
    assert client._build_id is None
    with client.build_snapshot():
        client.upsert_repo('a')
        assert not transaction.commit.called
    transaction.commit.assert_called_once()
    assert 'published_at' in transaction.run.call_args_list[-1].args[0]


def test_graph_identities_are_repository_scoped_and_unambiguous():
    assert entity_id('a', 'src/App.java') != entity_id('b', 'src/App.java')
    assert entity_id('a', 'GET', '/patient') != entity_id('b', 'GET', '/patient')
    assert entity_id('a::b', 'c') != entity_id('a', 'b::c')


def test_graph_writes_require_snapshot_and_constraints_errors_propagate():
    client = store()
    with pytest.raises(RuntimeError, match='build_snapshot'):
        client.upsert_repo('a')
    session = client._driver.session.return_value.__enter__.return_value
    session.run.side_effect = RuntimeError('permission denied')
    with pytest.raises(RuntimeError, match='permission denied'):
        client.ensure_constraints()


def test_repo_filter_belongs_to_endpoint_match_not_optional_caller_match():
    client = store()
    client.query_all_endpoints('backend')
    session = client._driver.session.return_value.__enter__.return_value
    query = session.run.call_args.args[0]
    assert query.index('WHERE $repo_name') < query.index('OPTIONAL MATCH')
    assert session.run.call_args.kwargs['repo_name'] == 'backend'


def test_missing_dependencies_are_recorded_with_context_and_type():
    client = store()
    with client.build_snapshot():
        client.link_dependencies('source', ['UnknownService', 'TwilioClient'], 'backend')
        dependencies = client._transaction.run.call_args.kwargs['dependencies']
        assert {dep['name']: dep['type'] for dep in dependencies} == {
            'UnknownService': 'missing_repo', 'TwilioClient': 'external_service',
        }
