from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sqlite3
from threading import RLock

from rank_bm25 import BM25Okapi

from core.config import get_settings
from core.models import DocumentChunk


def tokenize(text: str) -> list[str]:
    return re.findall(r'\w+', text.lower())


class BM25Index:
    """In-memory scorer with an optional transactional, cross-process corpus.

    SQLite persists source chunks, not pickled model objects. Each process
    refreshes its scorer when the shared revision changes.
    """

    def __init__(self, storage_path: str | Path | None = None):
        self.storage_path = Path(storage_path) if storage_path is not None else None
        self.chunk_map: dict[str, DocumentChunk] = {}
        self.chunks: list[DocumentChunk] = []
        self._bm25 = None
        self._revision = 0
        self._loaded_revision = -1
        self._lock = RLock()
        self._initialized = False

    def _connect(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=10)
        if not self._initialized:
            try:
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                connection.execute('CREATE TABLE IF NOT EXISTS index_state (key INTEGER PRIMARY KEY, revision INTEGER NOT NULL)')
                connection.execute('INSERT OR IGNORE INTO index_state VALUES (1, 0)')
                connection.commit()
                self._initialized = True
            except BaseException:
                connection.close()
                raise
        return connection

    def _refresh(self):
        if self.storage_path is None:
            return
        connection = self._connect()
        try:
            # Read revision + corpus from the same database snapshot.
            connection.execute('BEGIN')
            revision = connection.execute('SELECT revision FROM index_state WHERE key = 1').fetchone()[0]
            if revision != self._loaded_revision:
                rows = connection.execute('SELECT payload FROM chunks ORDER BY id').fetchall()
                chunks = [DocumentChunk.model_validate_json(row[0]) for row in rows]
                self.chunk_map = {chunk.id: chunk for chunk in chunks}
                self._rebuild()
                self._loaded_revision = revision
            self._revision = revision
        finally:
            connection.close()

    @property
    def revision(self) -> int:
        with self._lock:
            self._refresh()
            return self._revision

    def _update(self, chunks=(), removed=(), replace=False):
        with self._lock:
            if self.storage_path is None:
                if replace:
                    self.chunk_map.clear()
                for chunk_id in removed:
                    self.chunk_map.pop(chunk_id, None)
                self.chunk_map.update((chunk.id, chunk) for chunk in chunks)
                self._revision += 1
                self._rebuild()
                return
            connection = self._connect()
            try:
                with connection:
                    connection.execute('BEGIN IMMEDIATE')
                    if replace:
                        connection.execute('DELETE FROM chunks')
                    connection.executemany('DELETE FROM chunks WHERE id = ?', ((key,) for key in removed))
                    connection.executemany(
                        'INSERT OR REPLACE INTO chunks VALUES (?, ?)',
                        ((chunk.id, chunk.model_dump_json()) for chunk in chunks),
                    )
                    connection.execute('UPDATE index_state SET revision = revision + 1 WHERE key = 1')
            finally:
                connection.close()
            self._refresh()

    def add(self, chunks: list[DocumentChunk]):
        self._update(chunks=chunks)

    def remove(self, chunk_ids: list[str]) -> None:
        self._update(removed=chunk_ids)

    def replace(self, chunks: list[DocumentChunk]) -> None:
        """Atomically replace the derived corpus, e.g. during Qdrant recovery."""
        self._update(chunks=chunks, replace=True)

    def search(self, query: str, limit: int = 20, repo_name: str | None = None,
               language: str | None = None, section: str | None = None):
        with self._lock:
            self._refresh()
            if self._bm25 is None or limit < 1 or not tokenize(query):
                return []
            scores = self._bm25.get_scores(tokenize(query))
            ranked = sorted(enumerate(scores), key=lambda item: (-item[1], self.chunks[item[0]].id))
            out = []
            for index, score in ranked:
                chunk = self.chunks[index]
                if repo_name and chunk.repo != repo_name:
                    continue
                if language and chunk.language != language:
                    continue
                if section and section.lower() not in ' '.join(chunk.section_hierarchy).lower():
                    continue
                out.append({'id': chunk.id, 'score': float(score), 'payload': chunk.payload(), 'source': 'bm25'})
                if len(out) >= limit:
                    break
            return out

    def _rebuild(self) -> None:
        self.chunks = sorted(
            (chunk for chunk in self.chunk_map.values() if tokenize(chunk.text)),
            key=lambda chunk: chunk.id,
        )
        self._bm25 = BM25Okapi([tokenize(chunk.text) for chunk in self.chunks]) if self.chunks else None


settings = get_settings()
collection_key = hashlib.sha256(settings.collection_name.encode()).hexdigest()[:16]
bm25_index = BM25Index(Path(settings.local_data_dir) / f'bm25-{collection_key}.sqlite3')
