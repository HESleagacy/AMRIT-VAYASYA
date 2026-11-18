from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

from core.graph_builder import GraphBuilder
from core.graph_identity import entity_id


def test_dependencies_link_after_all_qdrant_pages_are_populated():
    builder = GraphBuilder.__new__(GraphBuilder)
    builder._collection = 'tests'
    builder._neo4j = MagicMock()
    builder._neo4j.link_http_calls_to_endpoints.return_value = 0
    builder._qdrant = Mock()
    builder._qdrant.scroll.side_effect = [
        ([SimpleNamespace(payload={
            'repo': 'backend', 'path': 'Controller.java', 'language': 'java',
            'classes': ['PatientController'], 'dependencies': ['PatientService'],
        })], 'next-page'),
        ([SimpleNamespace(payload={
            'repo': 'backend', 'path': 'Service.java', 'language': 'java',
            'classes': ['PatientService'],
        })], None),
    ]

    def link_dependencies(*args):
        assert builder._neo4j.upsert_class.call_count == 2

    builder._neo4j.link_dependencies.side_effect = link_dependencies
    assert builder.build()['resolved_links'] == 0
    builder._neo4j.link_dependencies.assert_called_once_with(
        entity_id('backend', 'Controller.java', 'PatientController'), ['PatientService'], 'backend',
    )
    assert builder._qdrant.scroll.call_args.kwargs['offset'] == 'next-page'
