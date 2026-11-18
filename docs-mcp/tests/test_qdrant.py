from unittest.mock import Mock

import httpx
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

from core.models import DocumentChunk
from core.qdrant.client import QdrantVectorStore


def test_vector_store_search_and_filters_with_in_memory_qdrant():
    store = QdrantVectorStore(collection='tests', dim=2)
    store.client = QdrantClient(':memory:')
    try:
        chunks = [
            DocumentChunk(
                id=f'00000000-0000-0000-0000-{index:012d}', repo=repo, path='app.py',
                language='python', text='patient', token_count=1, source_hash='test',
                section_hierarchy=['API'],
            )
            for index, repo in enumerate(('a', 'b'), start=1)
        ]
        store.upsert(chunks, [[1.0, 0.0], [0.0, 1.0]])
        hits = store.search([1.0, 0.0], repo_name='a', language='python', section='API')
        assert [hit['id'] for hit in hits] == [chunks[0].id]
        assert hits[0]['payload']['repo'] == 'a'
        store.delete([chunks[0].id])
        assert store.search([1.0, 0.0], repo_name='a') == []
    finally:
        store.client.close()


def test_legacy_qdrant_client_search_is_supported():
    store = QdrantVectorStore(collection='tests', dim=2)
    store.client = Mock(spec=['get_collections', 'search'])
    store.client.get_collections.return_value.collections = [Mock(name='tests')]
    store.client.get_collections.return_value.collections[0].name = 'tests'
    store.client.search.return_value = []
    assert store.search([1.0, 0.0]) == []
    assert store.client.search.call_args.kwargs['query_vector'] == [1.0, 0.0]


@pytest.mark.parametrize('status', [404, 500])
def test_new_client_handles_legacy_server_without_hiding_server_errors(monkeypatch, status):
    store = QdrantVectorStore(url='http://qdrant.test:6333', collection='tests', dim=2)
    store.client = Mock()
    store.client.get_collections.return_value.collections = [Mock()]
    store.client.get_collections.return_value.collections[0].name = 'tests'
    store.client.query_points.side_effect = UnexpectedResponse(
        status, 'error', b'{}', httpx.Headers(),
    )
    post = Mock(return_value=httpx.Response(
        200, json={'result': [{'id': '1', 'score': 0.9, 'payload': {'repo': 'a'}}]},
        request=httpx.Request('POST', 'http://qdrant.test:6333'),
    ))
    monkeypatch.setattr(httpx, 'post', post)
    if status == 500:
        with pytest.raises(UnexpectedResponse):
            store.search([1.0, 0.0])
        post.assert_not_called()
    else:
        hits = store.search([1.0, 0.0], repo_name='a')
        assert hits[0]['payload'] == {'repo': 'a'}
        assert post.call_args.args[0] == 'http://qdrant.test:6333/collections/tests/points/search'
        assert post.call_args.kwargs['json']['filter']['must'][0]['key'] == 'repo'
