import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.models import DocumentChunk, QueryRequest
from core.config import get_settings
from core.retrieval.bm25 import BM25Index
from core.retrieval.hybrid import HybridRetriever
from scripts.rebuild_keyword_index import rebuild


def chunk(key='a', text='patient registration'):
    return DocumentChunk(
        id=key, text=text, path='app.py', repo='backend', token_count=2, source_hash='test',
    )


def test_keyword_corpus_survives_process_restart_and_tracks_deletions(tmp_path):
    path = tmp_path / 'corpus.sqlite3'
    writer, reader = BM25Index(path), BM25Index(path)
    writer.add([chunk()])
    assert [item['id'] for item in reader.search('patient')] == ['a']
    previous = reader.revision
    writer.remove(['a'])
    assert reader.search('patient') == []
    assert reader.revision > previous
    assert BM25Index(path).search('patient') == []


def test_keyword_corpus_is_visible_to_a_separate_process(tmp_path):
    path = tmp_path / 'corpus.sqlite3'
    BM25Index(path).add([chunk()])
    code = (
        'from core.retrieval.bm25 import BM25Index; import sys; '
        "assert BM25Index(sys.argv[1]).search('patient')[0]['id'] == 'a'"
    )
    subprocess.run([sys.executable, '-c', code, str(path)], env=os.environ.copy(), check=True)


def test_keyword_recovery_is_atomic_when_qdrant_pagination_fails(tmp_path):
    index = BM25Index(tmp_path / 'corpus.sqlite3')
    index.add([chunk('old')])
    client = Mock()
    client.scroll.side_effect = [
        ([SimpleNamespace(payload=chunk('new').payload())], 'page-2'),
        RuntimeError('Qdrant unavailable'),
    ]
    with pytest.raises(RuntimeError):
        rebuild(client, index, 'test')
    assert [item['id'] for item in index.search('patient')] == ['old']


def test_shared_revision_invalidates_cached_query_keys(tmp_path, monkeypatch):
    from core.retrieval import hybrid

    index = BM25Index(tmp_path / 'corpus.sqlite3')
    monkeypatch.setattr(hybrid, 'bm25_index', index)
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.settings = get_settings()
    request = QueryRequest(query='patient')
    old = retriever._cache_key(request)
    BM25Index(index.storage_path).add([chunk()])
    assert retriever._cache_key(request) != old


def test_query_cache_is_scoped_to_collection_and_model_configuration(monkeypatch):
    from core.retrieval import hybrid

    monkeypatch.setattr(hybrid, 'bm25_index', BM25Index())
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.settings = get_settings().model_copy()
    request = QueryRequest(query='patient')
    baseline = retriever._cache_key(request)
    retriever.settings.collection_name = 'other-collection'
    assert retriever._cache_key(request) != baseline
    collection_key = retriever._cache_key(request)
    retriever.settings.reranker_model = 'other-model'
    assert retriever._cache_key(request) != collection_key


def test_empty_token_corpus_does_not_crash_and_unicode_is_searchable():
    index = BM25Index()
    index.add([chunk('empty', '!!!')])
    assert index.search('patient') == []
    index.add([chunk('hindi', 'नमस्ते दुनिया')])
    assert index.search('नमस्ते')[0]['id'] == 'hindi'


def test_successful_recovery_replaces_stale_keyword_chunks(tmp_path):
    index = BM25Index(tmp_path / 'corpus.sqlite3')
    index.add([chunk('old')])
    client = Mock()
    client.scroll.return_value = ([SimpleNamespace(payload=chunk('new').payload())], None)
    assert rebuild(client, index, 'test') == 1
    assert [item['id'] for item in index.search('patient')] == ['new']
