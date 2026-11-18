from types import SimpleNamespace
from unittest.mock import Mock

from core.evidence import BackendEndpoint, ApiContract, TraversalEvidence
from core.evidence_collector import EvidenceCollector


def make_collector(rows):
    collector = EvidenceCollector.__new__(EvidenceCollector)
    collector._neo4j = Mock()
    collector._neo4j.query_trace.return_value = rows
    collector._qdrant = Mock()
    collector._qdrant.scroll.return_value = ([], None)
    collector._collection = 'test_chunks'
    return collector


def test_collect_preserves_branches_and_repositories_without_duplicate_callers():
    row = {
        'method': 'GET', 'path': '/patient/{patientId}',
        'handler_class': 'PatientController', 'handler_kind': 'controller',
        'backend_repo': 'backend-a', 'backend_file': 'src/PatientController.java',
        'service_chain': ['PatientController', 'PatientService'],
        'frontend_callers': [{
            'caller': 'PatientComponent', 'repo': 'ui', 'file': 'patient.ts',
            'path': '/patient/123',
        }],
    }
    collector = make_collector([
        row,
        {**row, 'service_chain': ['PatientController', 'AuditService']},
        {**row, 'backend_repo': 'backend-b'},
    ])
    evidence = collector.collect('patient')

    assert len(evidence.backend_endpoints) == 2
    assert len(evidence.api_contracts) == 2
    assert evidence.service_chain == ['PatientController', 'PatientService', 'AuditService']
    assert len(evidence.frontend_components) == 1
    assert evidence.frontend_components[0].called_path == '/patient/123'
    assert evidence.backend_endpoints[0].api_contract.path_params == ['patientId']
    requested_classes = collector._qdrant.scroll.call_args.kwargs['scroll_filter'].must[0].match.any
    assert 'AuditService' in requested_classes


def test_supporting_chunks_and_contracts_are_scoped_to_repository():
    collector = make_collector([])
    collector._qdrant.scroll.return_value = ([
        SimpleNamespace(payload={
            'repo': repo, 'path': 'src/Controller.java',
            'classes': ['Controller'], 'text': dto,
        })
        for repo, dto in [('a', 'CreateRequest'), ('b', 'UpdateRequest')]
    ], None)
    evidence = TraversalEvidence(feature='patient')
    evidence.backend_endpoints = [
        BackendEndpoint(
            method='POST', path='/patient', normalized_path='/patient',
            repo=repo, handler_class='Controller', handler_kind='controller',
            backend_file='src/Controller.java',
            api_contract=ApiContract(endpoint_id=repo, request_dto=None, response_dto=None, path_params=[]),
        )
        for repo in ('a', 'b')
    ]
    collector._pull_supporting_chunks(evidence, ['Controller'])
    collector._enrich_api_contracts(evidence)

    assert len(evidence.supporting_chunks) == 2
    assert [ep.api_contract.request_dto for ep in evidence.backend_endpoints] == [
        'CreateRequest', 'UpdateRequest',
    ]


def test_close_releases_both_clients_even_if_neo4j_close_fails():
    import pytest

    collector = make_collector([])
    collector._neo4j.close.side_effect = RuntimeError('close failed')
    with pytest.raises(RuntimeError, match='close failed'):
        collector.close()
    collector._qdrant.close.assert_called_once()


def test_unresolved_hops_use_graph_evidence_and_are_deduplicated():
    collector = make_collector([])
    evidence = TraversalEvidence(feature='patient')
    missing = {'name': 'AuditService', 'type': 'missing_repo', 'context': 'Controller injection'}
    external = {'name': 'TwilioClient', 'type': 'external_service', 'context': 'Notification injection'}
    collector._detect_unresolved_hops(evidence, [
        {'unresolved_hops': [external, missing, {'name': None}]},
        {'unresolved_hops': [missing]},
    ])
    assert [(hop.name, hop.hop_type) for hop in evidence.unresolved_hops] == [
        ('AuditService', 'missing_repo'), ('TwilioClient', 'external_service'),
    ]
