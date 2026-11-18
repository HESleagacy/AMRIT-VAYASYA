"""Rebuild the local persistent keyword corpus from the configured Qdrant collection."""
from qdrant_client import QdrantClient

from core.config import get_settings
from core.models import DocumentChunk
from core.retrieval.bm25 import bm25_index


def rebuild(client, index, collection):
    chunks, offset = [], None
    while True:
        points, offset = client.scroll(
            collection_name=collection, offset=offset, limit=200,
            with_payload=True, with_vectors=False,
        )
        chunks.extend(DocumentChunk.model_validate(point.payload) for point in points)
        if offset is None:
            break
    # Do not replace a working corpus if retrieval or validation failed midway.
    index.replace(chunks)
    return len(chunks)


if __name__ == '__main__':
    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)
    try:
        print(f'Rebuilt {rebuild(client, bm25_index, settings.collection_name)} keyword chunks')
    finally:
        client.close()
