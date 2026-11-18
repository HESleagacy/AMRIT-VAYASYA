"""Run explicitly against a disposable Neo4j instance, never a production DB."""
from contextlib import contextmanager
import os
from uuid import uuid4

import pytest

from config import Settings
from core.graph_identity import entity_id
from core.neo4j_client import Neo4jClient


@pytest.fixture
def database(monkeypatch):
    uri = os.environ.get('VAYASYA_TEST_NEO4J_URI')
    if not uri:
        pytest.fail('Set VAYASYA_TEST_NEO4J_URI to a disposable Neo4j database')
    settings = Settings(
        _env_file=None, neo4j_uri=uri,
        neo4j_user=os.environ.get('VAYASYA_TEST_NEO4J_USER', 'neo4j'),
        neo4j_password=os.environ.get('VAYASYA_TEST_NEO4J_PASSWORD', 'test-password'),
        graph_namespace=f'integration-{uuid4().hex}',
    )
    monkeypatch.setattr('core.neo4j_client.get_settings', lambda: settings)
    client = Neo4jClient()
    client.ensure_constraints()
    builds, original = [], client.build_snapshot

    @contextmanager
    def tracked_snapshot():
        with original() as build_id:
            builds.append(build_id)
            yield build_id

    monkeypatch.setattr(client, 'build_snapshot', tracked_snapshot)
    try:
        yield client
    finally:
        with client._driver.session() as session:
            # Only entities/state owned by this test's random namespace/builds.
            session.run(
                'MATCH (n:VayasyaEntity) WHERE n.build_id IN $builds DETACH DELETE n',
                builds=builds,
            ).consume()
            session.run(
                'MATCH (s:VayasyaGraphState {key: $key}) DELETE s',
                key=settings.graph_namespace,
            ).consume()
        client.close()


def populate(client, repo, path='/patient/{id}', file_path='src/App.java'):
    client.upsert_repo(repo)
    client.upsert_file(file_path, repo, 'java', 'spring-boot')
    client.upsert_class('PatientController', 'controller', file_path, repo)
    client.upsert_class('PatientService', 'service', file_path, repo)
    controller_id = entity_id(repo, file_path, 'PatientController')
    client.upsert_endpoint('GET', path, controller_id, repo)
    client.link_dependencies(controller_id, ['PatientService', 'TwilioClient', 'MissingClient'], repo)


def test_repository_isolation_and_recorded_unresolved_hops(database):
    with database.build_snapshot():
        populate(database, 'a')
        populate(database, 'b')
        database.upsert_repo('ui')
        database.upsert_file('patient.ts', 'ui', 'typescript', 'angular')
        database.upsert_class('PatientComponent', 'component', 'patient.ts', 'ui')
        database.upsert_http_call(
            'GET', '/patient/42', entity_id('ui', 'patient.ts', 'PatientComponent'), 'ui',
        )
        assert database.link_http_calls_to_endpoints() == 2
    assert len(database.query_all_endpoints()) == 2
    assert len(database.query_all_endpoints('a')) == 1
    stats = database.stats()
    assert stats['files'] == 3
    assert stats['classes'] == 5
    assert stats['resolved_links'] == 2
    traces = database.query_trace('patient')
    assert {row['backend_repo'] for row in traces} == {'a', 'b'}
    hops = {
        (hop['name'], hop['type'])
        for row in traces for hop in row['unresolved_hops'] if hop['name']
    }
    assert hops == {('TwilioClient', 'external_service'), ('MissingClient', 'missing_repo')}
    assert database.query_dependencies('PatientController', 'a')[0]['dependencies'] == ['PatientService']


def test_successful_rebuild_removes_stale_results_and_failure_preserves_active_snapshot(database):
    with database.build_snapshot():
        populate(database, 'old', '/old')
        database.link_http_calls_to_endpoints()
    with database.build_snapshot():
        populate(database, 'new', '/new')
        database.link_http_calls_to_endpoints()
        # Reads during a rebuild must still see the previous published graph.
        assert [ep['path'] for ep in database.query_all_endpoints()] == ['/old']
    assert [ep['path'] for ep in database.query_all_endpoints()] == ['/new']
    with pytest.raises(RuntimeError, match='interrupted'):
        with database.build_snapshot():
            populate(database, 'broken', '/broken')
            raise RuntimeError('interrupted')
    assert [ep['path'] for ep in database.query_all_endpoints()] == ['/new']
    assert database.stats()['repos'] == 1


def test_empty_snapshot_clears_active_results_without_deleting_legacy_nodes(database):
    marker = 'integration-legacy-' + uuid4().hex
    with database._driver.session() as session:
        session.run(
            'CREATE CONSTRAINT integration_legacy_file IF NOT EXISTS '
            'FOR (f:File) REQUIRE f.path IS UNIQUE',
        ).consume()
        session.run('CREATE (:File {path: $path})', path=marker).consume()
    try:
        with database.build_snapshot():
            populate(database, 'old', file_path=marker)
            database.link_http_calls_to_endpoints()
        with database.build_snapshot():
            database.link_http_calls_to_endpoints()
        assert database.query_all_endpoints() == []
        assert database.stats()['endpoints'] == 0
        with database._driver.session() as session:
            assert session.run('MATCH (f:File {path: $path}) RETURN count(f) AS c', path=marker).single()['c'] == 1
    finally:
        with database._driver.session() as session:
            session.run('MATCH (f:File {path: $path}) DELETE f', path=marker).consume()


def test_active_graph_namespaces_do_not_leak_into_each_other(database):
    with database.build_snapshot():
        populate(database, 'first', '/first')
        database.link_http_calls_to_endpoints()
    other = Neo4jClient()
    other._graph_key += '-other'
    build_id = None
    try:
        with other.build_snapshot() as build_id:
            populate(other, 'second', '/second')
            other.link_http_calls_to_endpoints()
        assert [row['path'] for row in other.query_all_endpoints()] == ['/second']
        assert [row['path'] for row in database.query_all_endpoints()] == ['/first']
    finally:
        with other._driver.session() as session:
            session.run(
                'MATCH (n:VayasyaEntity {build_id: $build_id}) DETACH DELETE n',
                build_id=build_id,
            ).consume()
            session.run(
                'MATCH (s:VayasyaGraphState {key: $key}) DELETE s', key=other._graph_key,
            ).consume()
        other.close()
