from core.chunking.semantic import SemanticChunker
from core.metadata.enricher import MetadataEnricher
from core.models import ParsedDocument, ParsedSection

import pytest


def test_chunking_preserves_hierarchy_and_code_blocks():
    doc = ParsedDocument(
        repo_name='repo',
        path='README.md',
        language='markdown',
        text='# Architecture\nintro\n\n```python\nprint(1)\n```\n\n' + ('word ' * 900),
        headings=['Architecture'],
        sections=[
            ParsedSection(
                title='Architecture',
                level=1,
                kind='architecture',
                content='# Architecture\nintro\n\n```python\nprint(1)\n```\n\n' + ('word ' * 900),
                hierarchy=['Architecture'],
            )
        ],
    )
    doc = MetadataEnricher().enrich(doc)
    chunks = SemanticChunker(max_tokens=300, overlap=120).chunk(doc)
    assert chunks
    assert chunks[0].chunk_type.value == 'architecture'
    assert chunks[0].section_hierarchy == ['Architecture']
    assert any('```python' in chunk.text for chunk in chunks)


def test_long_paragraph_respects_limit_and_zero_overlap_without_losing_text():
    words = [f'word{index}' for index in range(103)]
    doc = ParsedDocument(path='README.md', language='markdown', text=' '.join(words))
    chunks = SemanticChunker(min_tokens=10, max_tokens=20, overlap=0).chunk(doc)
    assert len(chunks) == 6
    assert all(chunk.token_count <= 20 for chunk in chunks)
    assert ' '.join(chunk.text for chunk in chunks).split() == words
    assert chunks[0].prev_chunk_id is None
    assert chunks[-1].next_chunk_id is None
    assert chunks[1].prev_chunk_id == chunks[0].id
    assert chunks[0].created_at.utcoffset().total_seconds() == 0
    assert chunks[0].ingestion_timestamp.utcoffset().total_seconds() == 0


def test_code_fences_remain_atomic_even_when_larger_than_token_limit():
    code = '```python\n' + '\n'.join(f'print({index})' for index in range(30)) + '\n```'
    doc = ParsedDocument(path='README.md', language='markdown', text=code)
    chunks = SemanticChunker(min_tokens=1, max_tokens=20, overlap=0).chunk(doc)
    assert len(chunks) == 1
    assert chunks[0].text == code


@pytest.mark.parametrize('kwargs', [{'max_tokens': 0}, {'min_tokens': 0}, {'overlap': -1}])
def test_chunker_rejects_invalid_token_configuration(kwargs):
    with pytest.raises(ValueError, match='Token limits'):
        SemanticChunker(**kwargs)
